# Production Readiness & Architecture Recommendations

This document outlines the architectural improvements, security controls, persistence patterns, and operational practices required to transition the **Document Intake Assistant** from a demonstration prototype to an enterprise-grade production platform.

---

## 1. Persistence & State Management

### Current Implementation
- Sessions and `IntakeState` are stored in an in-memory dictionary within `SessionManager`.
- State is lost if the process restarts.

### Production Roadmap
- **Distributed Session Store**: Replace the in-memory dictionary with a high-availability **Redis** cluster or a managed **PostgreSQL** database.
  - Redis provides sub-millisecond session reads and native **TTL (Time-To-Live)** expiration for inactive intake sessions.
  - PostgreSQL allows relational storage of completed documents, user accounts, and immutable audit logs.
- **Session Expiration & Cleanup**: Implement automatic session expiration (e.g. 24 hours of inactivity) with background cleanup workers to prevent memory leaks and orphaned sessions.
- **Schema Migrations**: Use `Alembic` for database migrations as the `IntakeState` model evolves over time.

---

## 2. Horizontal Scaling & High Availability

### Current Implementation
- Single-process FastAPI server with local state.

### Production Roadmap
- **Stateless Application Tier**: By externalizing session state to Redis/PostgreSQL, FastAPI container instances become completely stateless.
- **Container Orchestration**: Deploy containers behind a cloud load balancer (e.g. AWS ALB, GCP Cloud Load Balancing) managed via **Kubernetes (EKS/GKE)** or **AWS ECS / Google Cloud Run**.
- **Autoscaling**: Scale container pods horizontally based on CPU utilization and incoming HTTP request concurrency.

---

## 3. LLM Reliability, Fallbacks & Cost Management

### Production Roadmap
- **Retries with Exponential Backoff & Jitter**: Wrap Gemini API calls with bounded retries (e.g., using `tenacity`) for transient `503 Service Unavailable` or `429 Rate Limit` responses.
- **Circuit Breakers**: Implement circuit breakers to stop overwhelming external AI endpoints during prolonged outages and immediately fall back to a secondary provider (e.g., Claude 3.5 or GPT-4o) or prompt the user gracefully.
- **Prompt Versioning & CI/CD Evaluation**: Version system prompts in code or a prompt management platform (e.g., Langfuse / Promptfoo) with automated regression evaluation suites before releasing prompt adjustments.
- **Token Usage & Cost Tracking**: Log token consumption per turn to monitor infrastructure costs and detect runaway loops.

---

## 4. Security & Compliance

### Production Roadmap
- **Secrets Management**: Retrieve `GEMINI_API_KEY` at runtime from a secure secret store (e.g., **AWS Secrets Manager**, **Google Secret Manager**, or **HashiCorp Vault**) rather than plain `.env` files on disk.
- **Authentication & Authorization**: Protect endpoints with **OAuth2 / JWT** tokens (e.g. via Auth0 or Clerk) ensuring users can only access their own session IDs.
- **Strict CORS & CSP**: Restrict CORS origins strictly to verified production domain names (`https://app.example.com`). Add Content Security Policy (CSP) headers to prevent XSS.
- **Rate Limiting**: Protect `/api/chat` and `/api/session` with IP-based and user-based rate limiters (e.g., `slowapi` backed by Redis) to prevent denial-of-service and API abuse.
- **Prompt Injection Defense**: Sanitize user inputs and employ guardrails (e.g., NeMo Guardrails or Llama Guard) to prevent adversarial prompt injection attacks aimed at manipulating extraction logic.

---

## 5. Observability & Telemetry

### Production Roadmap
- **Structured JSON Logging**: Replace standard console outputs with structured JSON logs containing timestamp, `session_id`, `request_id`, turn latency, and extraction status (avoiding logging sensitive PII).
- **Distributed Tracing**: Implement **OpenTelemetry** instrumentation across HTTP handlers, validation routines, and Gemini API calls to visualize end-to-end latency breakdowns in tools like Datadog or Jaeger.
- **Metrics & Alerting**: Export Prometheus metrics for:
  - API request throughput and HTTP status distributions (2xx, 4xx, 5xx).
  - LLM latency percentiles (p50, p95, p99).
  - Contradiction and clarification frequency rates.

---

## 6. Data Protection & Privacy (PII)

Because this application collects personal and estate-related details (names, residential addresses, family members, bequests), strict data protection measures are essential:

- **Encryption in Transit**: Enforce **TLS 1.3** on all external and internal network communications.
- **Encryption at Rest**: Encrypt stored sessions and draft documents using **AES-256** with customer-managed encryption keys (AWS KMS / GCP KMS).
- **Data Retention & Right to Erasure**: Provide explicit data retention policies and user-facing endpoints for immediate data deletion in compliance with **GDPR / CCPA**.
- **Audit Logging**: Maintain immutable, append-only audit logs recording who accessed or modified draft documents.

---

## 7. Why Deterministic Document Rendering Is Superior

In this application, draft documents are rendered deterministically in Python rather than generated by an LLM:

1. **Legal Predictability**: Eliminates the risk of the LLM hallucinating terms, omitting clauses, or altering formal disclaimers.
2. **Zero Additional Token Cost**: Document updates occur instantaneously with zero API overhead on every turn.
3. **Reproducibility & Auditability**: Identical structured state always produces the exact same document, essential for verifiable compliance.

---

## 8. Summary Comparison

| Capability | Current Demo Implementation | Production Architecture |
| :--- | :--- | :--- |
| **Session Persistence** | In-Memory (`dict`) | Distributed Redis + PostgreSQL |
| **Scaling** | Single Instance | Stateless Auto-scaling Containers (K8s) |
| **LLM Provider** | Mock / Single Gemini Endpoint | Multi-Provider Fallback + Circuit Breaker |
| **Authentication** | Anonymous Session UUID | OAuth2 / JWT User Auth |
| **Secrets** | Local `.env` | Cloud Secrets Manager (KMS) |
| **Observability** | Pytest + Console Logs | OpenTelemetry + Datadog / Prometheus |
| **Document Generation** | Deterministic Python Template | Deterministic Python / PDF Engine |
