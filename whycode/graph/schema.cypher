// WhyCode graph schema for Neo4j AuraDB, MULTI-REPOSITORY version (v3)
// This file is the source of truth. Apply it with `python scripts/apply_schema.py` (safe to re-run).
// Embedding size 384 assumes a local bge-small / MiniLM model; change if you use another.
//
// MULTI-REPO RULES (read first)
//   1. One :Repo node per ingested repository, id = "owner/name", lowercased (e.g. "psf/requests").
//   2. EVERY other node carries a `repo` property AND its id is prefixed with the repo:
//        "psf/requests#pr:1565"   "pallets/flask#pr:1565"   <- no collision between repos
//      Every id is built by whycode/ids.py as "<repo>#<kind>:<key>"; never build ids by hand.
//   3. EVERY query must filter on `repo = $repo`. A query without it can mix repositories.
//   4. All writes use MERGE on `id`, so re-running ingestion or the sync job never creates duplicates.
//   5. Re-extracting a source REPLACES its decisions: before writing, DETACH DELETE every
//      Decision that is DECIDED_IN that source, then MERGE the new ones. Never add duplicates.

// ---------- 1. Uniqueness constraints (`id` is globally unique because it carries the repo prefix) ----------
CREATE CONSTRAINT repo_id     IF NOT EXISTS FOR (n:Repo)        REQUIRE n.id IS UNIQUE;   // id = "psf/requests"
CREATE CONSTRAINT commit_id   IF NOT EXISTS FOR (n:Commit)      REQUIRE n.id IS UNIQUE;   // id = "<repo>#commit:<full sha>"
CREATE CONSTRAINT pr_id       IF NOT EXISTS FOR (n:PullRequest) REQUIRE n.id IS UNIQUE;   // id = "<repo>#pr:1565"
CREATE CONSTRAINT issue_id    IF NOT EXISTS FOR (n:Issue)       REQUIRE n.id IS UNIQUE;   // id = "<repo>#issue:812"
CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (n:Decision)    REQUIRE n.id IS UNIQUE;   // id = "<repo>#dec:<sha256(source id|prompt_version|index)[:16]>"
CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence)    REQUIRE n.id IS UNIQUE;   // id = "<repo>#ev:<source key>:<part>", see section 3
CREATE CONSTRAINT person_id   IF NOT EXISTS FOR (n:Person)      REQUIRE n.id IS UNIQUE;   // id = "<repo>#user:<github login>"  (activity is per repo)
CREATE CONSTRAINT file_id     IF NOT EXISTS FOR (n:File)        REQUIRE n.id IS UNIQUE;   // id = "<repo>#file:<current path>"
CREATE CONSTRAINT function_id IF NOT EXISTS FOR (n:Function)    REQUIRE n.id IS UNIQUE;   // id = "<repo>#fn:<path>::<qualified name>"
CREATE CONSTRAINT module_id   IF NOT EXISTS FOR (n:Module)      REQUIRE n.id IS UNIQUE;   // id = "<repo>#mod:requests.sessions"
CREATE CONSTRAINT config_id   IF NOT EXISTS FOR (n:ConfigKey)   REQUIRE n.id IS UNIQUE;   // id = "<repo>#cfg:max_retries"

// ---------- 2. Search indexes ----------
// Vector index: only used to find the ENTRY POINT into the graph, never to answer on its own.
// It covers all repos, so ALWAYS filter results by repo afterwards and ask for more hits (k = 30+) than you need.
CREATE VECTOR INDEX evidence_embedding IF NOT EXISTS
FOR (e:Evidence) ON (e.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

// Fulltext index for resolving "rebuild_auth" or "max_retries" in a question to code entities.
// Also covers all repos: add `WHERE node.repo = $repo` to every lookup.
CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
FOR (n:File|Function|Module|ConfigKey) ON EACH [n.name, n.qualified_name, n.aliases_text];

// Per-repo lookups (keep every screen fast when many repos are loaded)
CREATE INDEX decision_repo_status IF NOT EXISTS FOR (d:Decision)    ON (d.repo, d.status);
CREATE INDEX decision_date        IF NOT EXISTS FOR (d:Decision)    ON (d.decided_at);
CREATE INDEX commit_repo_date     IF NOT EXISTS FOR (c:Commit)      ON (c.repo, c.date);
CREATE INDEX pr_repo_number       IF NOT EXISTS FOR (p:PullRequest) ON (p.repo, p.number);
CREATE INDEX issue_repo_number    IF NOT EXISTS FOR (i:Issue)       ON (i.repo, i.number);
CREATE INDEX file_repo            IF NOT EXISTS FOR (f:File)        ON (f.repo);
CREATE INDEX person_repo          IF NOT EXISTS FOR (p:Person)      ON (p.repo);

// ---------- 3. Node properties (documented; Neo4j is schema-free so this is the contract) ----------
// Repo        {id, owner, name, url, status, stage, progress_pct, partial, size_cap_applied,
//              added_at, last_synced_at, last_commit_sha, last_pr_updated_at, last_issue_updated_at,
//              counts_commits, counts_prs, counts_issues, counts_decisions, prompt_version, schema_version, error}
//   status : QUEUED | INGESTING | READY | ERROR          (drives the repo dropdown and the progress screen)
//   stage  : fetch | parse | link | extract | supersession (matches the five stages on the Graph health screen)
//   partial: true while ingestion is unfinished, so answers show a "partial history" warning
//   last_*  : the cursors the sync job uses to ask GitHub only for what is new
//
// Every node below also has:  repo (string, e.g. "psf/requests")
// Commit      {id, repo, sha, message, date, additions, deletions}
// PullRequest {id, repo, number, title, state, merged, merged_at, merge_commit_sha, url, comment_count, updated_at}
// Issue       {id, repo, number, title, state, url, created_at, closed_at, updated_at, kind}   // kind: bug | incident | feature | question
//   Incident = an Issue that is a regression, outage or security report. Also give it the label :Incident.
// Evidence    {id, repo, source_type, source_id, text, url, date, author, embedding}   // source_type: pr_body | pr_comment | review_comment | issue_comment | commit_msg | doc
//   Evidence id parts (source key = the source node's key without the repo):
//     pr_body        "<repo>#ev:pr:5797:body"          issue body     "<repo>#ev:issue:812:body"
//     pr_comment     "<repo>#ev:pr:5797:ic:<id>"       issue_comment  "<repo>#ev:issue:812:ic:<id>"
//     review_comment "<repo>#ev:pr:5797:rc:<id>"       commit_msg     "<repo>#ev:commit:<sha>:msg"
//     doc            "<repo>#ev:doc:<path>"
// Decision    {id, repo, summary, rationale, alternatives, decided_at, status, evidence_kind,
//              extraction_confidence, model, prompt_version}
//   status        : ACTIVE | SUPERSEDED | PARTIAL
//   evidence_kind : EXPLICIT (rationale stated in text) | INFERRED (reconstructed from message/diff) -> drives confidence
//   decided_at    : stored as a Neo4j datetime (5b compares it with datetime($asOf))
//   id            : hash of (source id, prompt_version, position in the extraction output), never of LLM text,
//                   so a re-run produces the same ids (see rule 5 for re-extraction)
// Person      {id, repo, login, name, first_seen, last_seen, active}     // active = last_seen within ~18 months, in THIS repo
// File        {id, repo, path, name, aliases, aliases_text}
//   aliases      = list of earlier paths (requests/sessions.py -> src/requests/sessions.py)
//   aliases_text = the aliases joined with single spaces; fulltext cannot index a list, so entity_names uses this
// Function    {id, repo, name, qualified_name, file_path, aliases_text}
// Module      {id, repo, name}
// ConfigKey   {id, repo, name, qualified_name, aliases_text}

// ---------- 4. Relationships (both ends are always in the same repo) ----------
// (:PullRequest)-[:CONTAINS]->(:Commit)
// (:PullRequest)-[:CLOSES]->(:Issue)              // "fixes #N", API closing references
// (:Commit)-[:REFERENCES]->(:Issue|:PullRequest)  // "#N" in the message, incl. "(#6767)" in subjects
// (:Commit)-[:MODIFIES {added, removed}]->(:File|:Function|:ConfigKey)
// (:Commit)-[:REVERTS]->(:Commit)                 // from "Revert ..." commits and git revert trailers
// (:Module)-[:CONTAINS]->(:File)-[:CONTAINS]->(:Function)
// (:Person)-[:AUTHORED]->(:Commit|:PullRequest|:Issue|:Evidence)
// (:Person)-[:REVIEWED]->(:PullRequest)
// (:Decision)-[:AFFECTS]->(:File|:Function|:ConfigKey)
// (:Decision)-[:DECIDED_IN]->(:PullRequest|:Issue|:Commit)
// (:Decision)-[:SUPPORTED_BY {span_start, span_end}]->(:Evidence)   // a Decision with no SUPPORTED_BY is discarded
// (:Decision)-[:TRIGGERED_BY]->(:Issue)           // incident or bug that caused the decision
// (:Decision)-[:PROPOSED_BY|:APPROVED_BY]->(:Person)
// (:Decision)-[:SUPERSEDES {kind, confidence, evidence_id}]->(:Decision)
//      kind: 'reverses' | 'replaces' | 'refines'
//      'reverses' and 'replaces' retire the older decision; 'refines' keeps it PARTIAL.
// Repo membership is the `repo` property, not a relationship, so deleting a repo is one query (see 6).

// ---------- 5. Query patterns the agent will use ($repo is ALWAYS passed) ----------

// 5a. The CURRENT governing decision(s) for an entity, never a dead one.
//     "Head" = no later decision that reverses or replaces it.
//     <Label> is File | Function | ConfigKey, inserted by code from that fixed allowlist (labels cannot
//     be parameters); the label lets Neo4j use the id constraint instead of scanning every node.
// MATCH (e:<Label> {id: $entityId, repo: $repo})<-[:AFFECTS]-(d:Decision {repo: $repo})
// WHERE NOT EXISTS { MATCH (d)<-[s:SUPERSEDES]-(:Decision) WHERE s.kind IN ['reverses','replaces'] }
// MATCH (d)-[sb:SUPPORTED_BY]->(ev:Evidence)
// OPTIONAL MATCH (d)-[:PROPOSED_BY]->(p:Person)
// OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(i:Issue)
// RETURN d, collect(DISTINCT ev) AS evidence, collect(DISTINCT p) AS proposers, collect(DISTINCT i) AS triggers
// ORDER BY d.decided_at DESC;

// 5b. Full lineage for the "Decision history" screen, including as-of time travel.
// MATCH (e {id: $entityId, repo: $repo})<-[:AFFECTS]-(d:Decision {repo: $repo})
// WHERE d.decided_at <= datetime($asOf)
// OPTIONAL MATCH (d)-[s:SUPERSEDES]->(older:Decision)
// RETURN d, s, older ORDER BY d.decided_at;

// 5c. Who to ask: most recent authors/reviewers tied to the decision or entity, flagged active or not.
// MATCH (d:Decision {id: $decisionId, repo: $repo})-[:PROPOSED_BY|APPROVED_BY]->(p:Person)
// RETURN p.login, p.active, p.last_seen ORDER BY p.last_seen DESC;

// 5d. Hotspots for the Home screen: entities with the most reversed decisions IN THIS REPO.
// MATCH (e {repo: $repo})<-[:AFFECTS]-(d:Decision {repo: $repo})<-[s:SUPERSEDES {kind:'reverses'}]-(:Decision)
// RETURN e.id, e.name, count(DISTINCT d) AS reversals ORDER BY reversals DESC LIMIT 10;

// 5e. Entry point when no entity matches: vector search over evidence, then hop to its decisions.
// CALL db.index.vector.queryNodes('evidence_embedding', 40, $queryEmbedding) YIELD node AS ev, score
// WHERE ev.repo = $repo
// MATCH (ev)<-[:SUPPORTED_BY]-(d:Decision)-[:AFFECTS]->(e)
// RETURN e, d, ev, score ORDER BY score DESC LIMIT 8;

// 5f. Entity lookup from the question text (fulltext), filtered to the repo the user is viewing.
// CALL db.index.fulltext.queryNodes('entity_names', $text) YIELD node, score
// WHERE node.repo = $repo
// RETURN node, score ORDER BY score DESC LIMIT 5;

// 5g. Repo dropdown: every repository with status and freshness.
// MATCH (r:Repo) RETURN r.id, r.status, r.stage, r.progress_pct, r.partial, r.last_synced_at ORDER BY r.last_synced_at DESC;

// ---------- 6. Sync and repo lifecycle ----------
// Add a repo:   MERGE (r:Repo {id: $repo}) SET r.status = 'QUEUED', r.added_at = datetime(), r.partial = true;
//               then run the full ingestion, updating r.stage and r.progress_pct as each stage finishes,
//               and finish with SET r.status = 'READY', r.partial = false, r.last_synced_at = datetime().
// Keep it fresh: the sync job reads r.last_commit_sha / r.last_pr_updated_at / r.last_issue_updated_at,
//               asks GitHub only for newer items, MERGEs them by id, re-extracts only changed PRs/issues,
//               re-checks supersession only for entities touched by the new decisions, then moves the cursors.
// Remove a repo (all nodes tagged with it, in batches):
//               MATCH (n {repo: $repo}) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS;
