# Orchestrator Tool Use — Design Spec

## Contexte

L'orchestrateur produit aujourd'hui ses décisions en JSON texte libre, parsé manuellement par `parse_llm_decision`. Ce format est fragile : le LLM peut mal formater le JSON, ajouter du texte autour, ou utiliser des marqueurs markdown qui cassent le parsing.

On passe au **tool use natif** de l'API LLM. Le LLM appelle des tools structurés, l'API garantit le format. Plus de parsing JSON manuel.

## Architecture

L'orchestrateur devient une boucle ReAct identique aux agents :

1. Le LLM reçoit le prompt système + contexte workflow + 4 tools bindés
2. Il peut répondre en texte (message à l'utilisateur) ou appeler des tools
3. Chaque tool call est exécuté, le résultat renvoyé au LLM
4. La boucle continue jusqu'à réponse texte ou tool terminal (`ask_human`, `human_gate`)

## Les 4 tools

### `dispatch_agent(agent_id: str, task: str) → str`
Dispatche un agent spécialisé avec une mission précise.
- Vérifie que `agent_id` est dans `allowed_agents`
- Vérifie la détection de boucles (>3 dispatch sans progrès)
- Retourne le statut d'exécution
- Non terminal : la boucle continue

### `ask_human(message: str) → str`
Pose une question à l'utilisateur dans le chat.
- Crée une requête HITL (`hitl_requests`) avec le message
- Le message peut contenir le format `(((? ... )))` pour les questions structurées
- Terminal : arrête la boucle, attend la réponse utilisateur

### `human_gate(phase: str, next_phase: str) → str`
Demande validation de transition de phase.
- Dans le chat onboarding : matérialisé par un bouton "Next"
- Terminal : arrête la boucle, attend la validation

### `rag_search(query: str, top_k: int = 5) → str`
Recherche dans les documents projet (base vectorielle pgvector).
- Réutilise `rag_service.create_rag_tools()` existant
- Non terminal : la boucle continue avec les résultats

## Ce qui est supprimé

- `parse_llm_decision()` — plus de parsing JSON manuel
- Le format JSON imposé dans le prompt (`--- FORMAT DE SORTIE OBLIGATOIRE ---`)
- Le seuil de confiance (confidence threshold) — le LLM appelle un tool ou pas
- Les classes `RoutingDecision`, `RoutingAction`, `DecisionType`, `ActionType` pour le parsing
- La section `decision_history` au format JSON — remplacée par l'historique des tool calls

## Ce qui est gardé

- Détection de boucles : vérifiée dans `dispatch_agent` avant exécution
- Contexte workflow engine : passé dans le prompt système (phase, agents suggérés, deliverables)
- `allowed_agents` : vérifié dans `dispatch_agent`
- Deux modes (workflow / onboarding) avec le même jeu de tools

## Fichiers impactés

### `Agents/orchestrator.py`
- Créer les 4 tools comme fonctions LangChain `@tool`
- Remplacer l'appel LLM + `parse_llm_decision` par une boucle ReAct avec `bind_tools`
- Garder le contexte workflow engine dans le prompt
- Garder la détection de boucles dans `dispatch_agent`

### `Agents/gateway.py`
- Adapter `/invoke` : plus de champ `decisions` JSON dans la réponse
- Lire les tool calls et résultats depuis le state LangGraph
- Construire `output` et `agents_dispatched` depuis les tool calls

### `hitl/services/analysis_service.py`
- Adapter `_run_analysis_pipeline` : la réponse gateway n'a plus de `decisions`
- Les questions HITL sont créées directement par le tool `ask_human` (plus besoin de détecter `escalate_human` côté HITL)

## Vérification

- Lancer un onboarding complet : l'orchestrateur pose des questions via `ask_human`, dispatche des agents, utilise le RAG
- Vérifier dans Langfuse que les tool calls apparaissent correctement
- Vérifier que la détection de boucles fonctionne toujours
- Vérifier que `allowed_agents` est respecté
