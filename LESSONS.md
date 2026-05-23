# LESSONS — agflow.docker

Lessons learned from corrections and successful patterns during development.
Format: `- [module] short description of the lesson`
Keep under 50 lines. Consolidate similar lessons.

- [méthodo] Jamais proposer d'option quick-and-dirty / hardcode / "on cleanera plus tard" dans un menu de design. Toujours TOUJOURS faire propre. Si la tâche est déraisonnable, alerter l'utilisateur et découper plutôt que dégrader la qualité.
- [tests/infra] Les tests d'intégration et migrations s'exécutent UNIQUEMENT via `./scripts/run-test.sh` sur une machine éphémère créée pour l'occasion. INTERDICTION absolue de toucher un LXC dont le CTID n'est pas compris entre 400 et 499. Les prompts subagents doivent le rappeler explicitement et ne jamais vérifier via import Python seul — utiliser run-test.sh.
- [frontend/layout] Dans un item de grid CSS, `align-self: stretch` donne bien la hauteur mais ne la propage pas comme "définitive" pour les enfants flex. Toujours ajouter `h-full` sur le composant Card/wrapper direct, puis `min-h-0` sur les flex items intermédiaires (`Tabs`, `TabsContent`) pour que la chaîne `flex-1` se résolve correctement jusqu'aux scroll-containers internes.
- [frontend/layout] Radix `TabsContent` dans un conteneur `flex-col` : ajouter `data-[state=inactive]:hidden` sur chaque `TabsContent`. Sans ça, la classe Tailwind `flex` (spécificité 0,1,0) override l'attribut HTML `hidden` de Radix (même spécificité, Tailwind gagne car déclaré après), rendant les onglets inactifs visibles et partageant l'espace flex avec l'onglet actif.
