# Changelog & Roadmap

## Terminé ✅

### Infrastructure
1. Infrastructure LXC + Docker (5 containers opérationnels)
2. Volumes mappés sur l'hôte
3. OpenLIT observabilité dans docker-compose (port 3000)
4. Scripts utilitaires + script d'installation unifié (02)

### Agents & Orchestration
5. 13 agents avec registry JSON (zéro fichiers Python individuels)
6. Gateway v0.6.0 : persistence + direct routing + parallélisme + auto-dispatch workflow
7. Thread persistence PostgreSQL + `!reset`
8. Workflow engine — phases, transitions, parallel_groups, auto-dispatch
9. Auto-dispatch groupes séquentiels (A → B → C, max 5 niveaux)
10. Orchestrateur guidé par workflow engine (contexte enrichi)
11. Prompt orchestrateur + Lead Dev (fait ou délègue)
12. team_resolver — source unique de vérité pour les chemins

### LLM & Outils
13. Multi-modèles (llm_providers.json, 17 providers, 9 types)
14. Rate limit throttling multi-provider (20 retries, backoff ×2, cap 120s)
15. MCP lazy install + locks thread-safe (29 serveurs catalogue)
16. Voyage AI billing OK (RAG pgvector)

### Communication
17. Canaux factorisés (Discord + Email, extensible Telegram)
18. Interface Discord user-friendly (formatage, smart split 1900 chars)
19. Human gate via canal factorisé (30 min, 4 rappels)
20. Boucle conversationnelle ask_human via canal factorisé

### Équipes & Dashboard
21. Multi-équipes (teams.json, isolation par channel Discord)
22. Dashboard admin web (port 8080) — auth, git, gestion configs, channels, import/export, monitoring
23. Publication GitHub via Documentaliste
24. EventBus observabilité — bus d'events centralisé avec ring buffer, Langfuse handler, webhook dispatcher
25. Monitoring dashboard — events temps réel, logs Docker, état containers
26. Langfuse observabilité — self-hosted v3, CallbackHandler LangChain, BDD dédiée
27. MCP SSE Server — agents exposés comme tools MCP par équipe, auth HMAC signée

### HITL Console
28. Console HITL web (port 8090) — inbox, agents, membres, WebSocket temps réel
29. Auth locale (email/password) avec inscription en rôle `undefined`
30. Auth Google OAuth — Google Identity Services, config via hitl.json, restriction par domaine
31. Gestion utilisateurs admin — colonne auth_type, rôle `undefined` visible en rouge

### Dispatch & Cultures (2026-03-16)
32. Dispatch par livrables — chaque livrable = 1 appel agent distinct
33. Système de cultures — 31 locales, prompts localisés
34. Éditeur pipeline steps — split-panel, drag-drop, baguette magique
35. Onglet Prompts dans Templates — CRUD prompts par culture
36. Onglet Autres dans Templates — gestion des cultures disponibles

### Workflow & Catégories (2026-03-22)
37. Catégories de livrables — arborescence 2 niveaux, éditeur CRUD popup, dropdown par livrable

## À faire 🔧

1. **Publication Notion** — Token MCP 401 à corriger
2. **Tests end-to-end** — Cycle complet Discovery → Ship avec PerformanceTracker
3. **Long-term memory (LangMem)** — Mémoire sémantique cross-thread
4. **Cron jobs** — Tâches planifiées sur le graph
5. **Concurrency control** — Gérer les messages qui arrivent avant la fin du précédent
6. **Inter-team outbound** — Demander une analyse à une équipe étrangère
7. **Inter-team inbound** — Accepter un entrant d'une équipe étrangère

## Projet test : PerformanceTracker

- **Brief** : SaaS suivi performances sportives multi-disciplines
- **Stack** : Flutter Android + FastAPI + PostgreSQL
- **Modèle** : Freemium
- **Repo GitHub** : `gaelgael5/PerformanceTracker`
- **État** : Structure initialisée, Discovery en cours
