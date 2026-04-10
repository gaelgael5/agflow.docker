# Project Lifecycle — Data Flow Architecture

## Project Directory Structure

```
/root/ag.flow/projects/<slug>/
├── .project              ← uuid, team, language, repo URLs
├── docs/                 ← User-provided input documents
├── repo/                 ← Cloned Git repository (depth 1)
└── deliverables/         ← AI agent outputs by phase
    ├── discovery/
    │   ├── requirements_analyst.md
    │   ├── legal_advisor.md
    │   └── _synthesis.md
    ├── design/
    │   ├── architect.md
    │   ├── ux_designer.md
    │   ├── planner.md
    │   └── _synthesis.md
    ├── build/
    │   ├── lead_dev.md
    │   ├── qa_engineer.md
    │   └── _synthesis.md
    └── ship/
        ├── devops_engineer.md
        ├── docs_writer.md
        └── _synthesis.md
```

## Onboarding Flow

```mermaid
flowchart TD
    START([New Project]) --> SETUP[Step 1: Setup<br/>Name / Team / Language / Dates]
    SETUP --> CHECK{Project dir<br/>exists?}
    CHECK -->|No| CREATE[Create directory<br/>Write .project<br/>uuid + team + language]
    CHECK -->|Yes| CONFIRM{Confirm merge<br/>5 last UUID digits}
    CONFIRM -->|Correct| REUSE[Reuse existing project]
    CONFIRM -->|Incorrect| SETUP
    CREATE --> SOURCES
    REUSE --> SOURCES

    SOURCES[Step 2: Sources]
    SOURCES --> MODE{Source mode?}
    MODE -->|New| AI_PLAN
    MODE -->|Existing sources| SRC_INPUT
    MODE -->|Import archive| IMPORT

    SRC_INPUT[Add sources]
    SRC_INPUT --> DOC_UP[Upload docs → docs/]
    SRC_INPUT --> URL_AN[Analyze URL → LLM → docs/]
    SRC_INPUT --> GIT_CL{Repo in .project?}
    GIT_CL -->|Yes| GIT_PULL[git pull — refresh]
    GIT_CL -->|No| GIT_CLONE[git clone → repo/<br/>Add repo: url to .project]

    DOC_UP --> AI_PLAN
    URL_AN --> AI_PLAN
    GIT_PULL --> AI_PLAN
    GIT_CLONE --> AI_PLAN

    IMPORT[Upload archive .zip/.tar.gz] --> UUID_CHECK{UUID match<br/>existing project?}
    UUID_CHECK -->|Yes| MERGE[Update existing project]
    UUID_CHECK -->|No| NEW_IMPORT[Create from archive]
    MERGE --> AI_PLAN
    NEW_IMPORT --> AI_PLAN

    AI_PLAN[Step 3: AI Planning]
    AI_PLAN --> HAS_SRC{Has sources?}
    HAS_SRC -->|Yes| ANALYZE[Analyze docs + repo<br/>LLM synthesis<br/>Veuillez patienter...]
    HAS_SRC -->|No| CHAT[Chat: describe your project]
    ANALYZE --> CHAT
    CHAT --> ISSUES[Generate issues + relations]
    ISSUES --> REVIEW[Step 4: Review & Create]
```

## Agent Data Flow — Memory Layers

```mermaid
flowchart LR
    subgraph SHORT_TERM["Short Term — LangGraph State"]
        STATE[(thread state<br/>agent_outputs)]
    end

    subgraph LONG_TERM["Long Term — Filesystem"]
        DOCS[docs/]
        DELIV[deliverables/<br/>phase/agent.md]
        SYNTH[_synthesis.md<br/>per phase]
    end

    subgraph SEARCH["Semantic Search — pgvector"]
        PGV[(embeddings<br/>chunked deliverables)]
    end

    AGENT((Agent)) -->|writes| STATE
    AGENT -->|reads| STATE

    STATE -->|agent_complete| DELIV
    DELIV -->|index chunks| PGV

    AGENT -->|reads phase context| SYNTH
    AGENT -->|search_project_knowledge| PGV
    AGENT -->|reads user input| DOCS
```

## Phase Execution — Context Chain

```mermaid
sequenceDiagram
    participant U as User
    participant GW as Gateway
    participant WE as Workflow Engine
    participant A as Agent
    participant FS as Filesystem
    participant PG as pgvector

    U->>GW: Start project
    GW->>WE: get_agents_to_dispatch(discovery)
    WE-->>GW: [requirements_analyst, legal_advisor]

    loop For each agent in phase
        GW->>FS: Read _synthesis.md (previous phases)
        FS-->>GW: context
        GW->>A: Run agent (state + context)
        A->>PG: search_project_knowledge(query)
        PG-->>A: relevant passages
        A-->>GW: deliverable
        GW->>FS: Write deliverables/phase/agent.md
        GW->>PG: Index chunks (embeddings)
    end

    GW->>FS: Generate _synthesis.md for phase
    GW->>WE: check_phase_complete()
    WE-->>GW: phase complete → next phase
```

## .project File Format

```
uuid: 550e8400-e29b-41d4-a716-446655440000
team: team1
language: fr
repo: https://github.com/org/backend-api
repo: https://github.com/org/mobile-app
```

Each line is a key-value pair. Keys can repeat (`repo` for multiple repositories).
