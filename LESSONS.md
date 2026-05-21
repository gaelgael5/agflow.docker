# LESSONS — agflow.docker

Lessons learned from corrections and successful patterns during development.
Format: `- [module] short description of the lesson`
Keep under 50 lines. Consolidate similar lessons.

- [méthodo] Jamais proposer d'option quick-and-dirty / hardcode / "on cleanera plus tard" dans un menu de design. Toujours TOUJOURS faire propre. Si la tâche est déraisonnable, alerter l'utilisateur et découper plutôt que dégrader la qualité.
- [tests/infra] Les tests d'intégration et migrations s'exécutent UNIQUEMENT via `./scripts/run-test.sh` sur une machine éphémère créée pour l'occasion. INTERDICTION absolue de toucher un LXC dont le CTID n'est pas compris entre 400 et 499. Les prompts subagents doivent le rappeler explicitement et ne jamais vérifier via import Python seul — utiliser run-test.sh.
