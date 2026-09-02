# **Architectural Master Blueprint & 6-Sprint Execution Plan: Real Estate Voice AI Agent**

## **1\. Executive Summary & Team Operating Model**

This master plan lays out the 12-week (6-sprint) path to build an enterprise-grade, low-latency, full-duplex Real Estate Voice AI Agent MVP. The system is designed to handle inbound phone inquiries, qualify buyer/seller leads, query active MLS/property databases in real time, schedule site visits, and gracefully escalate to human agents when needed.

### **Team Structure & Work Allocation**

* **Dev A (Backend, Telephony & Real-Time Infra):** Focuses on SIP/WebRTC audio transport, LiveKit media server, Redis state management, low-level audio resampling, microservices routing, and DevOps.  
* **Dev B (AI Systems, Data & Tool Integrations):** Focuses on Gemini Multimodal Live API client, Voice Activity Projection (VAP) integration, PostgreSQL/pgvector RAG pipeline, tool execution schemas, and compliance guardrails.  
* **Product Lead / Biz (1 Person):** Focuses on real estate domain workflows, prompt engineering, agent persona tuning, test-case curation, pilot client onboarding, and compliance alignment.

## **2\. Six-Sprint Vertical Execution Plan**

### **Sprint 1 — The Vertical "Hello World" Voice Loop**

**Duration:** Weeks 1–2

#### **Objective**

Establish a fully functional, end-to-end voice loop: a user dials a phone number, the call connects over PSTN to a WebRTC bridge, raw audio streams to a native Speech-to-Speech (S2S) model, and the model streams spoken audio back to the caller under 600ms Time-To-First-Audio (TTFA).

#### **Business Outcome**

Proves the core feasibility of automated inbound phone call handling without human intervention, establishing the latency baseline for all future work.

#### **Technical Outcome**

Operational LiveKit SIP gateway bridging PSTN phone calls to WebRTC, streaming 16kHz PCM audio to Gemini Live API, maintaining an ephemeral session state in Redis.

#### **Features**

* Inbound PSTN Phone Number Provisioning (Twilio/Telnyx SIP Trunking).  
* LiveKit SIP-to-WebRTC Media Bridge.  
* Bidirectional Audio Resampling Pipeline (8kHz µ-law $\\leftrightarrow$ 16kHz PCM).  
* Gemini Live API WebSocket Client Integration.  
* Minimal In-Memory Session State Storage.

#### **Engineering Tasks**

| ID | Task Description | Domain | Complexity | Est. Effort | Dependencies | Parallel? |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| PROP-101 | Provision Twilio/Telnyx SIP trunk and DID numbers | Telephony | S | 0.5 days | None | Yes (Dev A) |
| PROP-102 | Deploy LiveKit Media Server \+ LiveKit SIP Gateway on cloud VM | Infra/DevOps | M | 1.5 days | PROP-101 | No |
| PROP-103 | Build C/Rust-bound audio resampler (8kHz G.711 $\\leftrightarrow$ 16kHz PCM) | Backend | M | 2.0 days | PROP-102 | Yes (Dev A) |
| PROP-104 | Implement WebSockets client for Gemini Live API bidirectional stream | AI/ML | L (High Uncertainty) | 3.0 days | None | Yes (Dev B) |
| PROP-105 | Build basic Orchestrator event loop connecting LiveKit audio frames to Gemini | Backend | L | 2.5 days | PROP-103, PROP-104 | No |
| PROP-106 | Integrate Redis instance for ephemeral call session ID mapping | Database | S | 0.5 days | None | Yes (Dev A) |
| PROP-107 | Create basic unit tests for audio frame chunking (20ms frames) | Testing | S | 0.5 days | PROP-103 | Yes (Dev A) |
| PROP-108 | Implement basic TLS encryption on WebSockets and WebRTC channels | Security | S | 0.5 days | PROP-102 | Yes (Dev A) |
| PROP-109 | Document Sprint 1 local setup and deployment steps | Docs | S | 0.5 days | PROP-105 | Yes (Biz/Devs) |

#### **Dependencies**

Twilio/Telnyx account, GCP API access for Gemini Live API.

#### **Deliverables**

A runnable server environment where dialing a test phone number connects the caller to Gemini Live API for a continuous, real-time voice conversation.

#### **Definition of Done**

* Caller dials PSTN number; call connects within 2 seconds.  
* Bidirectional voice conversation functions without dropping connections for at least 3 minutes.  
* Average Time-To-First-Audio (TTFA) is measured under 600ms.  
* Zero audio buffer overflows or sample-rate distortion artifacts.

#### **Demo Scenario**

Product Lead calls the test phone number from a mobile phone, says *"Hello, I'm looking to buy a house,"* and the AI agent verbally responds in natural English within 500ms acknowledging the statement.

#### **Risks & Mitigation**

* *Risk:* Latency spikes due to WebSocket audio streaming overhead.  
* *Mitigation:* Pre-allocate raw byte buffers in memory; avoid JSON wrapping of raw PCM audio payloads.

#### **Stretch Goals**

Inject basic vocal greeting prompt directly upon SIP connection before caller speaks.

### **Sprint 2 — Predictive Turn-Taking, Interruption & State**

**Duration:** Weeks 3–4

#### **Objective**

Implement natural, human-like conversation flow by deploying Voice Activity Projection (VAP), Acoustic Echo Cancellation (AEC), and instant barge-in handling to process user interruptions cleanly.

#### **Business Outcome**

Prevents the AI from sounding like a rigid IVR system; allows callers to interrupt mid-sentence without audio overlapping or confusion.

#### **Technical Outcome**

Parallel execution of Silero VAD / VAP models alongside audio transport, clearing outbound playout buffers within 50ms upon user speech detection.

#### **Features**

* Predictive Turn-Taking Engine using Voice Activity Projection (VAP).  
* Acoustic Echo Cancellation (AEC3) filtering.  
* Asynchronous Full-Duplex Interruption (Barge-in) Buffer Clearing.  
* Short-Term Conversation Memory Manager in Redis.  
* Basic Structured Event Logging (OpenTelemetry traces for speech events).

#### **Engineering Tasks**

| ID | Task Description | Domain | Complexity | Est. Effort | Dependencies | Parallel? |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| PROP-201 | Integrate WebRTC AEC3 module into LiveKit audio pipeline | Telephony | M | 1.5 days | PROP-102 | Yes (Dev A) |
| PROP-202 | Deploy lightweight Silero VAD / VAP sidecar service for speech detection | AI/ML | L (High Uncertainty) | 3.0 days | PROP-105 | Yes (Dev B) |
| PROP-203 | Build CLEAR\_BUFFER event bus signal from VAP to LiveKit audio queue | Backend | M | 2.0 days | PROP-201, PROP-202 | No |
| PROP-204 | Implement transcript truncation in Redis context window upon barge-in | Backend | M | 1.5 days | PROP-106, PROP-203 | Yes (Dev A) |
| PROP-205 | Develop system prompt template for Real Estate Assistant persona | AI/ML | S | 1.0 days | None | Yes (Biz/Dev B) |
| PROP-206 | Build OpenTelemetry logging middleware tracking call ID and latency | Infra | S | 1.0 days | PROP-105 | Yes (Dev A) |
| PROP-207 | E2E Automated Voice Testing for Interruption Scenarios | Testing | M | 1.0 days | PROP-203 | No |
| PROP-208 | Document Turn-Taking state machine and buffer clearing specs | Docs | S | 0.5 days | PROP-203 | Yes (Biz) |

#### **Dependencies**

Sprint 1 completed audio pipeline (PROP-105).

#### **Deliverables**

An updated voice pipeline where speaking while the agent is talking instantly silences the agent, updates conversation history to what was actually heard, and yields the turn.

#### **Definition of Done**

* Agent stops speaking within \< 80ms of caller starting to speak during agent playback.  
* Redis context window accurately truncates text to match the word spoken at the exact millisecond of interruption.  
* False positive interruptions (coughing, ambient car noise) remain below 10%.

#### **Demo Scenario**

Caller asks agent to describe a 5-bedroom home. While the agent is mid-sentence reciting amenities, caller interrupts: *"Wait, how many bathrooms?"* The agent stops instantly and answers the bathroom question without finishing its previous sentence.

#### **Risks & Mitigation**

* *Risk:* VAP model introduces GPU compute overhead and increases server costs.  
* *Mitigation:* Run quantized ONNX versions of Silero VAD / VAP on CPU workers.

#### **Stretch Goals**

Tune VAP pitch-drop detection to distinguish between thinking pauses ("*uhm...*") and true completion pauses.

### **Sprint 3 — Property Knowledge Base, RAG & Function Calling**

**Duration:** Weeks 5–6

#### **Objective**

Connect the Core Brain to structured real estate listing databases and unstructured brochure documents using real-time Retrieval-Augmented Generation (RAG) and function calling.

#### **Business Outcome**

Enables the AI agent to answer complex listing inquiries (pricing, HOA fees, floor plans, zoning, school ratings) with zero hallucination.

#### **Technical Outcome**

PostgreSQL \+ pgvector database setup, FastAPI Tool Router microservice, and asynchronous function execution loop that injects listing data into Gemini context within 400ms.

#### **Features**

* PostgreSQL \+ pgvector Schema for Property Listings & Document Embeddings.  
* Vector Search RAG Pipeline for unstructured brochures and FAQs.  
* Tool Router Service for S2S Function Calling (search\_properties, get\_property\_details).  
* Interactive Vocal Filler Engine (masks tool latency by prompting natural filler speech).

#### **Engineering Tasks**

| ID | Task Description | Domain | Complexity | Est. Effort | Dependencies | Parallel? |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| PROP-301 | Design & deploy PostgreSQL schema for listings, projects, and pgvector | Database | M | 1.5 days | None | Yes (Dev A) |
| PROP-302 | Build listing ingestion script (PDF/Text to chunks $\\rightarrow$ OpenAI/Gemini Embeddings) | AI/ML | M | 2.0 days | PROP-301 | Yes (Dev B) |
| PROP-303 | Build FastAPI Tool Router service handling function-call payloads | Backend | M | 2.0 days | PROP-105 | Yes (Dev A) |
| PROP-304 | Implement search\_properties tool schema & SQL execution logic | Backend/DB | L | 2.5 days | PROP-301, PROP-303 | No |
| PROP-305 | Build Interactive Vocal Filler generator in Orchestrator for API calls \> 500ms | AI/ML | M (High Uncertainty) | 2.0 days | PROP-204, PROP-303 | Yes (Dev B) |
| PROP-306 | Integration testing for tool execution latency and context injection | Testing | S | 1.0 days | PROP-304 | No |
| PROP-307 | Implement SQL injection prevention and schema parameter validation | Security | S | 0.5 days | PROP-304 | Yes (Dev A) |
| PROP-308 | Document API tool schemas and property database fields | Docs | S | 0.5 days | PROP-304 | Yes (Biz) |

#### **Dependencies**

Sprint 2 state manager (PROP-204).

#### **Deliverables**

A Voice AI agent that can query a live database of 100+ real estate listings mid-call and accurately answer questions about specific home features.

#### **Definition of Done**

* Agent successfully parses user intent, triggers search\_properties tool call, executes SQL/vector query, and speaks the answer.  
* Total latency from user question to start of answer (including DB query) is kept under 900ms (or masked with filler speech within 300ms).  
* Zero database hallucinations on pricing or bedroom counts across 20 test queries.

#### **Demo Scenario**

Caller asks: *"Do you have any 3-bedroom houses in North Austin under $550,000?"* Agent says *"Let me check our active listings in North Austin..."* (filler), queries database, and replies *"Yes, we have two listings. The first is on Oak Street for $520,000..."*

#### **Risks & Mitigation**

* *Risk:* Database vector search takes \> 1 second, causing awkward silence.  
* *Mitigation:* Enforce strict 350ms DB timeout; return partial keyword results if vector search exceeds deadline.

#### **Stretch Goals**

Implement geocoding API integration to answer *"How far is this house from the nearest airport?"*

### **Sprint 4 — Lead Qualification Engine & Action Tools**

**Duration:** Weeks 7–8

#### **Objective**

Implement automated BANT (Budget, Authority, Need, Timeline) lead qualification logic, calendar availability querying, and site-visit appointment scheduling.

#### **Business Outcome**

Transforms the voice bot from an informational agent into a revenue-generating Inside Sales Agent (ISA) that books qualified appointments directly for field agents.

#### **Technical Outcome**

State-machine lead scorer writing to PostgreSQL CRM tables, Google Calendar / Outlook API integration for slot booking, and Twilio SMS/WhatsApp automated notification dispatch.

#### **Features**

* Lead Extraction Engine (Extracts Budget, Timeline, Intent, Financing status).  
* Appointment Scheduling Engine (check\_calendar\_slots, book\_site\_visit).  
* Twilio SMS / WhatsApp API confirmation dispatch.  
* Lead Scoring & Priority Assignment Model.  
* PostgreSQL CRM Database Persistence.

#### **Engineering Tasks**

| ID | Task Description | Domain | Complexity | Est. Effort | Dependencies | Parallel? |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| PROP-401 | Expand PostgreSQL schema for contacts, leads, appointments, interactions | Database | M | 1.5 days | PROP-301 | Yes (Dev A) |
| PROP-402 | Build BANT qualification state extraction parser in Core Brain | AI/ML | L | 2.5 days | PROP-204, PROP-401 | Yes (Dev B) |
| PROP-403 | Integrate Google Calendar API / Cal.com API for slot reading and booking | Backend | M | 2.0 days | PROP-303 | Yes (Dev A) |
| PROP-404 | Build SMS/WhatsApp dispatch service via Twilio messaging API | Backend | S | 1.0 days | PROP-403 | Yes (Dev A) |
| PROP-405 | Build lead scoring rules engine (High/Medium/Low priority tagger) | Backend/AI | M | 1.5 days | PROP-402 | Yes (Dev B) |
| PROP-406 | End-to-end API testing for appointment booking and lead capture | Testing | S | 1.0 days | PROP-403, PROP-404 | No |
| PROP-407 | Implement API key encryption for third-party calendar integrations | Security | S | 0.5 days | PROP-403 | Yes (Dev A) |
| PROP-408 | Create BANT conversation design matrix and prompt rules | Docs | S | 0.5 days | None | Yes (Biz) |

#### **Dependencies**

Sprint 3 Tool Router (PROP-303).

#### **Deliverables**

A voice agent capable of dynamically asking qualification questions, matching caller availability against an agent's calendar, locking in a showing slot, and sending a confirmation text message.

#### **Definition of Done**

* Agent correctly collects Budget, Timeline, and Purchasing intent during conversation.  
* Site visit booked via API appears accurately on Google Calendar.  
* Confirmation SMS received on caller's mobile phone within 10 seconds of call booking confirmation.

#### **Demo Scenario**

Caller says: *"I want to visit the Oak Street house."* Agent asks: *"Great\! Are you pre-approved for a mortgage, and when are you looking to buy?"* Caller answers. Agent checks calendar, offers *"I have tomorrow at 2 PM open,"* locks the slot, and dispatches a text confirmation to the caller.

#### **Risks & Mitigation**

* *Risk:* Calendar double-booking if two calls occur simultaneously.  
* *Mitigation:* Implement Redis distributed locking (Redlock) on calendar slot keys during booking execution.

#### **Stretch Goals**

Implement automated email summary dispatch containing call audio recording link.

### 

### 

### **Sprint 5 — Fallback Systems, Human Escalation & Compliance**

**Duration:** Weeks 9–10

#### **Objective**

Ensure 100% operational reliability by deploying a Cascaded Fallback Pipeline (STT $\\rightarrow$ LLM $\\rightarrow$ TTS), live SIP warm/cold transfer to human brokers, and real-time Fair Housing compliance guardrails.

#### **Business Outcome**

Protects the brokerage from dropped calls and legal liability (Fair Housing violations) while providing a safety net for high-value clients who demand human interaction.

#### **Technical Outcome**

Cascaded fallback engine (Deepgram \+ GPT-4o-mini \+ Cartesia), SIP REFER / INVITE human transfer mechanism with context payload, and real-time compliance token filtering.

#### **Features**

* Cascaded Fallback Pipeline (Deepgram STT \+ LLM \+ Cartesia TTS).  
* Live SIP Human Call Transfer Engine (transfer\_to\_human\_agent).  
* Pre-Transfer Context Payload Generator (SMS/Webhook to agent before transfer).  
* Fair Housing & Regulatory Compliance Token Filter.  
* PII Redaction Engine for call transcripts and logs.

#### **Engineering Tasks**

| ID | Task Description | Domain | Complexity | Est. Effort | Dependencies | Parallel? |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| PROP-501 | Build Cascaded Fallback pipeline (Deepgram WebSocket \+ GPT-4o-mini \+ Cartesia) | AI/Backend | XL (High Uncertainty) | 3.5 days | PROP-105 | Yes (Dev B) |
| PROP-502 | Build Health Monitor to auto-switch to Fallback if S2S latency \> 1200ms or drops | Infra/Backend | M | 2.0 days | PROP-501 | Yes (Dev A) |
| PROP-503 | Implement SIP REFER / Twilio Call Transfer to bridge call to human broker | Telephony | L | 2.5 days | PROP-101, PROP-204 | Yes (Dev A) |
| PROP-504 | Build pre-transfer webhook sending AI summary & BANT state to broker phone | Backend | S | 1.0 days | PROP-402, PROP-503 | No |
| PROP-505 | Implement Fair Housing compliance filter (blocks demographic/steering queries) | AI/ML | M | 1.5 days | PROP-205 | Yes (Dev B) |
| PROP-506 | Add automated PII masking (regex \+ Presidio) for transcripts stored in DB | Security/DB | M | 1.5 days | PROP-401 | Yes (Dev A) |
| PROP-507 | Stress testing fallback switches during active voice calls | Testing | S | 1.0 days | PROP-502 | No |
| PROP-508 | Document Compliance Rules and Escalation Workflows | Docs | S | 0.5 days | None | Yes (Biz) |

#### **Dependencies**

Sprint 2 state management, Sprint 4 CRM schemas.

#### **Deliverables**

A fault-tolerant voice platform that seamlessly transfers callers to a human broker with context when asked, automatically blocks illegal responses, and fails over to a secondary voice stack if the primary S2S API degrades.

#### **Definition of Done**

* SIP Transfer connects caller to human broker's cell phone within 5 seconds of request.  
* Broker receives an SMS summary of caller's budget and target property before answering the bridged call.  
* System auto-switches to Cascaded Fallback when Gemini API returns 5xx errors or drops.  
* 100% of demographic/steering questions (e.g., *"Is this a Christian neighborhood?"*) receive compliant, non-discriminatory canned responses.

#### **Demo Scenario**

> 1. Caller asks: *"Are the local residents mostly white?"* Agent immediately detects compliance violation and responds: *"I cannot provide demographic information, but I can share local school ratings and official community statistics."*  
> 2. Caller says: *"I need to speak to a real person right now."* Agent says *"Connecting you to our lead broker, Sarah..."*, dispatches SMS context to Sarah, and bridges the call to her cell phone.

#### **Risks & Mitigation**

* *Risk:* Human broker does not answer transferred phone call.  
* *Mitigation:* Implement fallback voicemail capture service with priority transcript tagging.

#### **Stretch Goals**

Dual-tone multi-frequency (DTMF) touch-tone key detection for phone tree navigation.

### **Sprint 6 — Hardening, Observability, Multi-Tenancy & Pilot Launch**

**Duration:** Weeks 11–12

#### **Objective**

Harden system stability under high call volume, deploy multi-tenant database isolation, complete end-to-end failure testing, build operational Grafana dashboards, and execute the soft pilot launch.

#### **Business Outcome**

Delivers a commercial-grade, multi-tenant SaaS MVP ready to handle live inbound traffic for initial real estate agency clients with full operational visibility.

#### **Technical Outcome**

PostgreSQL Row-Level Security (RLS) multi-tenancy, Grafana monitoring dashboards (TTFA, Call Drops, Tool Errors), and end-to-end automated call scenario test suites.

#### **Features**

* Multi-Tenant Data Isolation Architecture (PostgreSQL Row-Level Security).  
* Grafana Operational & Quality Dashboards (OpenTelemetry \+ Prometheus).  
* Automated End-to-End Voice Scenario Test Battery (50 call scenarios).  
* Tenant Admin Dashboard API for listing upload and prompt configuration.  
* Production Deployment on Scalable Kubernetes / Container Infra.

#### **Engineering Tasks**

| ID | Task Description | Domain | Complexity | Est. Effort | Dependencies | Parallel? |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| PROP-601 | Implement PostgreSQL Row-Level Security (RLS) for tenant\_id isolation | Database | M | 2.0 days | PROP-401 | Yes (Dev A) |
| PROP-602 | Build Tenant Admin API endpoints for uploading listings and calendar keys | Backend | M | 2.0 days | PROP-601 | Yes (Dev A) |
| PROP-603 | Build Grafana dashboards tracking TTFA, Call Volumes, CSAT, and Tool Errors | Infra/DevOps | M | 1.5 days | PROP-206 | Yes (Dev A) |
| PROP-604 | Implement Automated E2E Voice Scenario Test Runner (50 audio scenarios) | Testing/AI | L | 2.5 days | All Sprints | Yes (Dev B) |
| PROP-605 | Conduct Load Testing (simulate 50 concurrent WebRTC calls via Locust/LiveKit) | Testing/Infra | M | 1.5 days | PROP-102 | No |
| PROP-606 | Security audit & secret rotation setup (HashiCorp Vault / AWS Secrets Manager) | Security | S | 1.0 days | All Sprints | Yes (Dev A) |
| PROP-607 | Create Agency Onboarding Guide & API Documentation | Docs | S | 1.0 days | None | Yes (Biz) |
| PROP-608 | Soft Launch Pilot Deployment for Agency Partner 1 | Operations | M | 2.0 days | All Tasks | All Team |

#### **Dependencies**

Sprints 1 through 5 completed.

#### **Deliverables**

A fully production-ready, multi-tenant AI Voice Agent SaaS platform processing live calls for real estate pilot clients with real-time telemetry and safety guardrails.

#### **Definition of Done**

* Multi-tenant isolation verified: Tenant A cannot view or retrieve Tenant B's listings or leads under any query context.  
* System handles 20 concurrent voice calls without audio jitter or TTFA exceeding 800ms.  
* Grafana dashboard displays real-time metrics for live call volume, latency breakdown, and tool success rate.  
* Pilot agency partner successfully receives and processes 50+ live inbound caller inquiries.

#### **Demo Scenario**

Full End-to-End Pilot Workflow: Live phone number assigned to Agency Partner A. Caller dials in, inquires about a property, gets qualified, books a site visit, receives an SMS confirmation, and the agency owner views the new qualified lead and transcript on their isolated portal dashboard.

#### **Risks & Mitigation**

* *Risk:* Unexpected API rate limits on Gemini Live API during traffic spikes.  
* *Mitigation:* Pre-purchase provisioned throughput quotas; configure instant fallback to OpenAI Realtime or Cascaded Stack.

#### **Stretch Goals**

Automated CSAT post-call SMS survey dispatch.

## **3\. Comprehensive Testing Strategy**

### **Test Categories & Methodology**

> 1. **Unit Testing:** PyTest / Go Test covering unit audio resamplers, BANT state parsers, SQL query generators, and text tokenizers (\> 80% coverage target).  
> 2. **Integration Testing:** FastAPI TestClient testing tool calls against isolated staging PostgreSQL and Redis instances.  
> 3. **API Testing:** Automated Postman/Hoppscotch suites testing Google Calendar, Twilio SMS, and CRM webhooks.  
> 4. **Voice / Conversation Testing:** Audio injection framework playing synthetic WAV files directly into WebRTC streams and evaluating JSON output events.  
> 5. **End-to-End (E2E) Call Testing:** Telephony test harness dialing SIP DIDs, executing pre-scripted multi-turn conversations, and verifying audio responses.  
> 6. **Failure Testing:** Simulated network packet loss (10–30%), random API 500 errors, mid-call WebSocket drops, and database connection timeouts.  
> 7. **Load Testing:** Distributed Locust workers establishing 50 to 200 concurrent LiveKit WebRTC sessions to benchmark CPU/RAM usage and TTFA degradation.  
> 8. **Security Testing:** OWASP API vulnerability scanning, prompt injection attack batteries (jailbreak attempts), and tenant cross-contamination checks.

### **Matrix of Specific Real Estate Voice Test Cases**

| Scenario \# | Conversational Test Scenario | Expected System Behavior | Verification Metric |
| :---- | :---- | :---- | :---- |
| **1** | Simple Inquiry | Answers price, beds, and baths accurately from DB. | 100% data match against DB. |
| **2** | Reservation / Site Visit | Checks calendar, offers slot, books visit, dispatches SMS. | Calendar entry created & SMS delivered. |
| **3** | Unrelated Question ("What's the weather?") | Politeness pivot: answers briefly, pivots back to property. | Context retained; pivot executed. |
| **4** | Caller Interrupts Mid-Sentence | Playout buffer stops \< 80ms; parses new question. | Zero audio overlap; correct turn shift. |
| **5** | Caller Changes Mind ("Actually 3 beds, not 2") | Clears prior DB search state; re-queries for 3 beds. | State vector updated in Redis. |
| **6** | Caller Frustrated ("You're unhelpful\!") | Empathy response: lowers tone, offers human escalation. | Sentiment detected; escalation offered. |
| **7** | AI Does Not Know Answer | Acknowledges limit, offers to record note for listing agent. | Zero hallucination on unknown fields. |
| **8** | Slot Fully Booked | Identifies conflict, queries next 3 available slots, presents top choice. | Zero double-booking. |
| **9** | Customer Asks for Manager | Triggers transfer\_to\_human\_agent tool call immediately. | Transfer event emitted within 1 sec. |
| **10** | Manager Takeover / Transfer | Executes SIP REFER; sends SMS context to human broker cell. | Call bridged; SMS delivered. |
| **11** | Call Drops Mid-Conversation | Saves state to PostgreSQL; sends SMS: *"We got disconnected. Reconnect?"* | Recovery SMS dispatched \< 30 sec. |
| **12** | Backend Action / API Fails | Spoke filler: *"Having trouble reaching the system, but I noted your request."* | User experiences zero line drop. |
| **13** | Ambiguous Info ("Looking for something cheap") | Asks clarifying question: *"Understood\! What's your target price ceiling?"* | Clarification prompt executed. |
| **14** | Customer Asks for Illegal Discount | Explains pricing policy firmly and offers to submit written offer. | Policy compliance maintained. |
| **15** | Prompt Injection / Steering Violation | Intercepts phrase; speaks neutral Fair Housing disclosure. | Non-discrimination maintained. |

## **4\. AI Evaluation Framework**

To measure AI accuracy objectively, all call sessions pass through an automated post-call LLM-as-a-Judge evaluation worker (using GPT-4o) that scores the conversation against ten key metrics.  
![][image1]

### **Metric Specifications & Computational Formulae**

1\. Task Completion Rate (TCR)  
   Formula: (Successful Tasks Completed / Total Intended Tasks) \* 100  
   Measurement: Evaluated by LLM Judge scanning transcript against call intent tag. Target: \> 85%.

2\. Booking Accuracy (BA)  
   Formula: (Correct Calendar Bookings / Total Booking Attempts) \* 100  
   Measurement: DB record vs. Audio transcript timestamp comparison. Target: 100%.

3\. Hallucination Rate (HR)  
   Formula: (Factually Incorrect Statements / Total Factual Claims) \* 100  
   Measurement: Automated cross-check of transcript text against retrieved RAG context. Target: \< 1%.

4\. Escalation Accuracy (EA)  
   Formula: (Valid Escalations / Total Escalation Triggers) \* 100  
   Measurement: Evaluates if human handoff occurred appropriately without false positives. Target: \> 90%.

5\. Intent Classification Accuracy (ICA)  
   Formula: (Correctly Classified Intents / Total User Turns) \* 100  
   Measurement: Logged intent tag vs. ground-truth evaluated intent. Target: \> 92%.

6\. Response Latency (TTFA)  
   Formula: Timestamp(First Audio Byte Sent) \- Timestamp(User Finished Speaking)  
   Measurement: OpenTelemetry span duration in milliseconds. Target: \< 600ms.

7\. Interruption Handling Accuracy (IHA)  
   Formula: (Successful Buffer Clears / Total Interruption Events) \* 100  
   Measurement: Evaluated via audio stream energy drop checks post-interrupt. Target: \> 95%.

8\. Word Error Rate (WER \- Transcription)  
   Formula: (Substitutions \+ Deletions \+ Insertions) / Total Words Spoken  
   Measurement: Evaluated on sample audio recordings against human ground-truth transcripts. Target: \< 8%.

9\. Customer Satisfaction Score (CSAT)  
   Formula: Average score (1 to 5\) from post-call automated SMS survey.  
   Measurement: Direct user feedback rating via SMS reply. Target: \> 4.2 / 5.0.

10\. Qualification Capture Rate (QCR)  
    Formula: (Successfully Extracted BANT Fields / Total BANT Fields) \* 100  
    Measurement: Extracted CRM JSON state vs. raw transcript context. Target: \> 80%.

## **5\. Observability & Autopsy Architecture**

### **Structured Logging Schema**

All microservices emit structured JSON logs tagged with unified correlation IDs (call\_id, session\_id, tenant\_id).

JSON  
{  
  "timestamp": "2026-11-15T14:22:01.452Z",  
  "level": "INFO",  
  "correlation\_id": {  
    "call\_id": "call\_livekit\_99f8a12",  
    "session\_id": "sess\_redis\_4402a",  
    "tenant\_id": "agency\_austin\_realty"  
  },  
  "service": "core-orchestrator",  
  "event": "tool\_execution\_completed",  
  "metrics": {  
    "execution\_time\_ms": 312,  
    "ttfa\_ms": 520  
  },  
  "payload": {  
    "tool\_name": "search\_properties",  
    "params": {"beds": 3, "max\_price": 550000},  
    "result\_count": 2  
  }  
}

### **Post-Call Autopsy Framework ("What Went Wrong?")**

When a call fails (e.g., call drops, customer hangs up angrily, tool errors out, or latency exceeds 2000ms), the system automatically triggers an **Autopsy Pipeline**:

\[Failed Call Event\]   
        │  
        ▼  
\[Fetch OpenTelemetry Trace Span\] ➔ \[Fetch Redis Transcript Window\] ➔ \[Fetch Tool Logs\]  
        │  
        ▼  
\[GPT-4o Diagnostic Worker\]  
        │  
        ▼  
\[Generates RCA Payload\]  
  • Root Cause (e.g., "SIP Gateway RTP Packet Loss", "Database Timeout", "S2S Rate Limit")  
  • Exact Millisecond Phase of Failure  
  • Recommended Engineering Action  
        │  
        ▼  
\[Posts Alert to Slack / Grafana Alertmanager\]

## **6\. Security, Privacy & Multi-Region Compliance**

### **MVP Security Core**

* **Authentication & Authorization:** JWT-based service-to-service auth; PostgreSQL Row-Level Security (RLS) enforcing strict tenant isolation (WHERE tenant\_id \= current\_setting('app.current\_tenant')).  
* **Secrets Management:** Environment variables managed via AWS Secrets Manager / HashiCorp Vault; zero hardcoded keys in repos.  
* **API & Database Security:** TLS 1.3 in transit; AES-256 encryption at rest; parameterized SQL queries to prevent injection.  
* **PII Masking:** Real-time Presidio/Regex masking engine scrubbing names, credit cards, SSNs, and phone numbers before writing transcripts to persistent storage.

### **Multi-Regional Regulatory Landscape**

| Region | Primary Legal Framework | Voice AI Engineering Requirements |
| :---- | :---- | :---- |
| **United States** | **TCPA & Fair Housing Act** | • Prior express consent before automated outbound calling. • Strict compliance guardrails blocking demographic steering. • Mandatory disclosure: *"I am an AI assistant..."* |
| **India** | **DPDP Act 2023 & TRAI DND** | • Scrub against National Do-Not-Call (DND) registry before dialing. • Consent manager capturing explicit opt-in data. • Local data residency: Store Indian citizen voice data within local AWS/GCP regions. |
| **UAE** | **PDPL (Law No. 45/2021) & TDRA** | • Explicit consent required for voice recording and processing. • TDRA VoIP regulatory compliance (licensed SIP trunking via e& / du). • Cross-border data transfer restrictions outside UAE without approval. |

## **7\. Cost Analysis & Financial Scaling Models**

### **Operational Infrastructure Burn per Sprint (Development Phase)**

* *Sprints 1–2:* \~$150 / month (Twilio DIDs, LiveKit Cloud, Gemini Live API testing).  
* *Sprints 3–4:* \~$350 / month (Added PostgreSQL DB, Pinecone/Qdrant, Redis).  
* *Sprints 5–6:* \~$750 / month (Added Staging servers, Fallback ElevenLabs/Deepgram usage, Load testing).

### **Post-Launch Scaling Unit Cost Model**

> **Assumptions:** Average call duration \= **3 minutes**.  
> Cost calculations reflect operational unit pricing per active minute.

| Component | Cost per Minute | 100 Calls/mo (300 mins) | 1,000 Calls/mo (3k mins) | 10,000 Calls/mo (30k mins) | 100,000 Calls/mo (300k mins) |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **Telephony (Telnyx/Twilio SIP)** | $0.006 / min | $1.80 | $18.00 | $180.00 | $1,800.00 |
| **LiveKit Media RTC Bridge** | $0.010 / min | $3.00 | $30.00 | $300.00 | $3,000.00 |
| **Gemini Live API (S2S Engine)** | $0.023 / min | $6.90 | $69.00 | $690.00 | $6,900.00 |
| **PostgreSQL, pgvector, Redis** | Fixed \+ Vol. | $25.00 | $45.00 | $150.00 | $650.00 |
| **Monitoring, Tracing & Logs** | Fixed \+ Vol. | $10.00 | $20.00 | $80.00 | $400.00 |
| **Hosting (Kubernetes/VMs)** | Fixed | $40.00 | $80.00 | $250.00 | $1,200.00 |
| **Total Monthly Cost** | — | **$86.70** | **$262.00** | **$1,650.00** | **$13,950.00** |
| **Effective Cost per Call** | — | **$0.86 / call** | **$0.26 / call** | **$0.165 / call** | **$0.139 / call** |

## **8\. Master Timeline, Architecture & Decision Matrices**

### **A. 12-Week Master Timeline**

| Sprint | Weeks | Core Objective | Major Deliverable | Primary Risk |
| :---- | :---- | :---- | :---- | :---- |
| **Sprint 1** | W1–W2 | Vertical Voice Loop | PSTN-to-WebRTC-to-S2S voice connectivity | High streaming audio latency |
| **Sprint 2** | W3–W4 | Turn-Taking & Interruptions | Full-duplex conversation with \< 80ms barge-in | False positive interruptions |
| **Sprint 3** | W5–W6 | Property RAG & Tool Router | Vector search & database tool execution | Slow DB query latency |
| **Sprint 4** | W7–W8 | Lead Qualification & Booking | BANT extraction & calendar booking engine | Slot double-booking |
| **Sprint 5** | W9–W10 | Fallbacks & Human Escalation | Cascaded failover & live SIP broker transfer | Human transfer line drops |
| **Sprint 6** | W11–W12 | Hardening, Multi-Tenancy & Launch | Multi-tenant production MVP & Pilot Launch | Multi-tenant data leak |

### **B. Subsystem Dependency Map**

![][image2]

### **C. Progressive Architecture Evolution**

* **End of Sprint 1:** Single monolithic process connecting LiveKit WebRTC directly to Gemini Live API WebSocket. Ephemeral memory in local RAM.  
* **End of Sprint 3:** Decoupled microservices architecture. Core Orchestrator (Rust/Python) talking to separate VAP service, FastAPI Tool Router, Redis cache, and PostgreSQL database.  
* **End of Sprint 6:** Enterprise Multi-Tenant cloud environment. LiveKit cluster behind load balancer, PostgreSQL with Row-Level Security, automated Cascaded Fallback pipeline, OpenTelemetry tracing, and Grafana monitoring.

### **D. MVP Feature Priority Matrix**

| Feature | Sprint | Priority | Status at MVP Launch |
| :---- | :---- | :---- | :---- |
| **Inbound SIP Call Handling** | Sprint 1 | P0 (Critical) | Production Ready |
| **Sub-600ms Response Latency** | Sprint 1 | P0 (Critical) | Production Ready |
| **Full-Duplex Interruption (Barge-in)** | Sprint 2 | P0 (Critical) | Production Ready |
| **Property Listing RAG Search** | Sprint 3 | P0 (Critical) | Production Ready |
| **Site Visit Calendar Booking** | Sprint 4 | P0 (Critical) | Production Ready |
| **Automated SMS Confirmation** | Sprint 4 | P1 (High) | Production Ready |
| **Human Agent SIP Transfer** | Sprint 5 | P0 (Critical) | Production Ready |
| **Cascaded Voice Fallback** | Sprint 5 | P1 (High) | Production Ready |
| **Fair Housing Compliance Filter** | Sprint 5 | P0 (Critical) | Production Ready |
| **Multi-Tenant Data Isolation** | Sprint 6 | P0 (Critical) | Production Ready |
| **Admin Configuration Portal** | Sprint 6 | P2 (Medium) | Basic MVP API |

### **E. Technology Decision Matrix**

| Subsystem Component | Selected Option | Considered Alternatives | Trade-Off Analysis | MVP Recommendation |
| :---- | :---- | :---- | :---- | :---- |
| **Telephony Gateway** | **LiveKit SIP** | Twilio Media Streams, Telnyx WebSockets | LiveKit offers native WebRTC bridging, lower latency, and unified agent SDKs compared to WebSocket proxies. | **LiveKit SIP** |
| **S2S AI Engine** | **Gemini Live API** | OpenAI Realtime API, Cascaded STT-LLM-TTS | Gemini Live provides sub-300ms latency at a fraction of OpenAI Realtime API cost ($0.023 vs $0.05/min). | **Gemini Live API** |
| **Primary Database** | **PostgreSQL \+ pgvector** | Pinecone \+ MongoDB, Qdrant \+ MySQL | Single database stack simplifies ACID transactions for CRM data while handling vector similarity searches. | **PostgreSQL \+ pgvector** |
| **Session Cache** | **Redis** | Memcached, In-Memory Dict | Redis offers ultra-fast pub/sub messaging and persistent key-value caching required for full-duplex session state. | **Redis** |
| **Tool Router API** | **FastAPI (Python)** | Node.js Express, Go Fiber | FastAPI provides rapid async development with native Pydantic data validation matching LLM JSON schemas. | **FastAPI** |

### **F. Comprehensive Risk Register**

| Risk Event | Severity | Impact Area | Mitigation Strategy |
| :---- | :---- | :---- | :---- |
| **S2S API Latency Degradation** | **Critical** | User Experience | Deploy automated health monitor auto-switching to Cascaded Fallback (Deepgram \+ Cartesia) when latency \> 1200ms. |
| **Property Double Booking** | **High** | Business Operations | Implement Redis distributed locking (Redlock) on calendar keys during scheduling execution. |
| **Fair Housing Steering Violation** | **Critical** | Legal / Compliance | Intercept all model output text tokens through an inline compliance guardrail enforcing canned disclosure statements. |
| **Multi-Tenant Data Contamination** | **Critical** | Security / Privacy | Enforce PostgreSQL Row-Level Security (RLS) linked strictly to authenticated tenant JWT tokens. |
| **High Audio Jitter / Packet Loss** | **Medium** | Voice Quality | Utilize WebRTC over UDP with LiveKit's dynamic Google Congestion Control (GCC) jitter buffers. |

## **9\. Definition of MVP & Pilot Rollout Plan**

### **MVP Readiness Criteria**

The product is declared **MVP-Ready** at the end of Sprint 6 if and only if all the following quantitative thresholds are satisfied:

> 1. **Call Reliability:** $\\ge 98\\%$ of inbound calls connect and complete without unexpected line disconnections.  
> 2. **Conversational Speed:** Mean Time-To-First-Audio (TTFA) remains $\< 600\\text{ ms}$ on standard turns.  
> 3. **Booking Accuracy:** $100\\%$ of scheduled site visits are accurately reflected in Google Calendar without double-bookings.  
> 4. **Barge-in Performance:** Speech interruption halts agent audio playout within $\< 80\\text{ ms}$.  
> 5. **Compliance:** $0\\%$ leakage of Fair Housing demographic steering violations across 100 benchmark test queries.  
> 6. **Tenant Isolation:** Zero data leaks verified across multi-tenant penetration test battery.

### **Eight-Stage Real Estate Pilot Rollout Plan**

Stage 1: Partner Onboarding  
  │ • Sign pilot agreement with real estate brokerage partner.  
  │ • Import 50 active MLS/listing property records into PostgreSQL/pgvector.  
  ▼  
Stage 2: Portal Configuration  
  │ • Configure agency branding, business hours, and agent calendar OAuth tokens.  
  │ • Assign dedicated inbound SIP phone number (DID) to agency tenant.  
  ▼  
Stage 3: Internal Dry-Run Testing  
  │ • Agency brokers conduct 30 simulated phone calls covering edge-case scenarios.  
  │ • Fine-tune prompt persona and vocal filler parameters based on feedback.  
  ▼  
Stage 4: Soft Launch (After-Hours Traffic)  
  │ • Route after-hours inbound calls (6 PM – 8 AM) to AI Voice Agent.  
  │ • Human brokers handle daytime traffic; AI acts as night-time Inside Sales Agent (ISA).  
  ▼  
Stage 5: Operational Monitoring  
  │ • Engineering team monitors real-time Grafana dashboards (TTFA, Call Drops, Tool Execution).  
  │ • LLM-as-a-Judge post-call worker evaluates daily call logs and task completion rates.  
  ▼  
Stage 6: Daytime Overflow Scaling  
  │ • Expand AI agent coverage to daytime overflow calls when human agents are busy or showing properties.  
  ▼  
Stage 7: Feedback & Iteration Loop  
  │ • Weekly review with brokerage lead: review lead qualification capture rate and CSAT scores.  
  │ • Deploy prompt updates and tool adjustments in bi-weekly patch releases.  
  ▼  
Stage 8: Full Commercial Rollout  
  │ • Transition agency partner from pilot tier to full commercial SaaS subscription.

## **10\. Critical Technical Clarification Questions**

Before starting Sprint 1, the following critical questions must be confirmed:

> 1. **Primary Geographic Market & Regulatory Scope:** Which target geography will the initial pilot launch in first (**US**, **India**, or **UAE**)? *Reason:* This dictates immediate telephony DID purchasing, local server hosting region selection (for DPDP/PDPL data residency compliance), and legal caller disclosure requirements.  
> 2. **Primary Listing Source & Ingestion Standard:** Will active property listings be uploaded manually as brochures/PDFs via an Admin Portal, or do we need a live API connector to a specific Multiple Listing Service (MLS) or CRM platform (e.g., Follow Up Boss, kvCORE, Realtracs) during Sprint 3?

[image1]: <data:image/png;base64,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>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAnAAAAGUCAYAAAC1Lh+qAABhEklEQVR4Xu29ae8dxZ23T2bTaDJbZuYF8Ap4kgd+wLNISDxAQkgghKwRyJFlJUJGINvCCkTj2GJsZBYTcNgNAgIMOIYYYzDEclhuMCQxBmODzR4gLAGzGLyw9P2/6n9/z9SvuvucPr/N5zhXSZdOd1VXdW3d9Tnfqu4+7rjjjquC73znO9U//MM/VN/97ndFREREZMRAp/0/3fa/Aq48SERERERGi7/6q7+aKOD+8R//UURERERGmL//+7//XwHHzj/90z+JiIiIyIiTBBxr38oAERERERlNkoD7u7/7u1qAiIiIiIwmScD98z//s4iIiIiMCUnA/cu//IuIiIiIjAnH8Shq6SkiIiIio8txrH/713/9VxEREREZE45jHvV73/ueiIiIiIwJx5UeIiIiIjLaHPdv//ZvlYiIiIiMDwo4ERERkTHjuH//93+vRERERGR8UMCJiIiIjBnH/cd//EclIiIiIuODAk5ERERkzFDAiYiIiIwZCjgRERGRMUMBJyIiIjJmKOBERERExgwFnAzF8ccfX/OT8eHkk0+u+YmIyPgx6wLuxRdfTOzcubO6/fbba+E//elPq08//TRx3nnnJb+zzjqrevbZZ3txcwi/9dZbqwsvvHBCOhxPvDL9HOKV6QFxy2NLHnrooerzzz9PnHLKKbXwyXLjjTdWK1asqPkfbU488cRUN99++21PBPRrky6cdtppFe7VV1+tvv/97/f8o1737dvXWrfvvvtuipvHm052795dvfbaazX/krY+NKjv5f2nXzmnm8svv7w6dOhQdcUVV9TCRERkfJh1AVe6yy67rBeGoPvqq6+qAwcOVF988UV1+PDh6uabb65+/OMfp4GuyRHvt7/9bbVnz54kMiItjideef4c4jU54pbHljBwc86DBw8mIVKGTxbqYPXq1TX/o822bduqb775pvr973/f8+vXJl3Amvfxxx+nusz9EUDULSKtrW4RQMQt/acL+t59991X8y9p60OD+l4Iv0HlnAn4c/TJJ59UixYtqoWJiMh4MOsCLoQVg/eqVauqDz74oDrzzDPTAMZAxsASx7JdDtIMmOXgiN/XX3+drFflecrzNxECsfQfROR5OgffURVwWG3efPPNxik46n8y9dePmajbrsyZMyf1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RVrnnntuEhl33XVXLd0453QKuBysV4i5zZs39/z6CbhNmzalaUemH5usd02QR+LmfpSJNXQIox07dlT79u2r7r333urjjz9O7VCet6mc5LutbhFrO3fuTCJx48aN1erVq9P5iDfonCtWrEjiFNHHMWFNFRERkcGMlYDjaU4Ge4QGQi78se60pZmvgeNVIYiG8pg4broEHHn5+c9/PsEvhE/s9xNwTfkYBAIpt34hsBC57777brJwhZAjjPV4iNk8fls5EXBtdUsczrF79+5q5cqV1W9+85vqk08+SWGDzhn5++lPf1p99tlnPWuqiIiIDOaoCDiEVP4KjXitCIvYES+sR2O9FNv5wwtYbZi2i6nU8Geb6TnSWrRoUXpNxxNPPJHCcgHHPk+g5mvh8nMiQspzrlmzJr3S5KKLLqrWrl2b1reVZSrByoe18Ne//nXKD2v3EEdYqOI1Inv37k3plq8RmayA4zyIJ9agMaWMeKKuli9fnsqK+MWid8oppyQRizDL47eVkwc/qFv8y7pl/Rvr4FijF23wzDPPpLAu50TkESe3poqIiMhgjoqAK11YeBBbpcutVAzyDPbxMEMOogLRhEMoxNRjKeCA40I0DTonwuThhx/uhXV5BQlxeAI0d6xnwz8sb6WLuJMVcHDxxRf30kPAXXvttb0wRHI43oFXWtvaykk9Urfh8rrlYQWmT+fNm5f2cfGAQ9dzkl5uTRUREZHBzLqAm0mYlkP88FuGTZXSMtcFXpUxmXhTISyKTU/LYvHKX73SRFt+8Z9M3Q46J5ZWnz4VEREZjmNKwMl4sHTp0uqVV15J6/YuvfTSWriIiIj0RwEns855552XppF98lRERGRyKOBERERExgwFnIiIiMiYoYATERERGTMUcB2Yyqs9RERERKYbBVwHFHAiIiIySijgOqCAExERkVFCAdcBBZyIiIiMEgq4DijgREREZJRQwHVAASciIiKjhAKuAwo4ERERGSUUcB1QwImIiMgooYDrgAJORERERgkFXAcUcCIiIjJKKOA6oIATERGRUUIB1wEFnIiIiIwSCrgOKOBERERklFDAdUABJyIiIqOEAq4DCjgREREZJRRwHXjooYeq+fPn1/xFREREjgYKOBEREZExQwEnIiIiMmYo4ERERETGDAWciIiIyJihgBMREREZMxRwIiIiImOGAq6FBQsW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tYgcCyjg+rBkyZLyPl87RkTGC69rETkWUMAN4ODBg72b/I4dO2rhIjJ+eF2LyLijgBvA888/n27yhw4dqlasWFELF5Hxw+taRMYdBdwA5syZU+3bt69as2ZNLUxExhOvaxEZdxRwHVi7dm114okn1vxFZHzxuhaRcUYBJyIiIjJmKOBERERExgwFnIiIiMiYoYATERERGTMUcCIiIiJjhgJOREREZMxQwImIiIiMGQo4EfmL5Le//W314x//uOYvIjIOKOBE5C8SBZyIjDMKODnmWLhwYfX2229XZ555Zi1MJFDAicg4M+sC7vjjj6+uuOKK6vPPP68++OCD6oQTTqgdM9vs2bMn5ef++++vTj755Fr4sNx4443VRx99VPOX/+XFF1+sUR4zWW6//fb0ofKrrrqqFiYSKOBEZJyZdQG3bdu26ttvv02C6eDBg2ngPprfI7zzzjurr7/+ujpw4EAa9N96660pW24QEIcPH675TwdnnXVW9eyzz9b8p8qtt95aPffcczX/maLJlcd0pew/WuCkCwo4ERlnZlXAYX374osvqqVLl/b8du7cWV122WW9fSxyd999d3XTTTdNiHfOOeekmy0Chvgcs3r16gnHLF68OAmy888/v3buJtavX5/EW+yfdtpp1bvvvpssg23nLC2GiIQyLyHgTj311FQO8lSeu19eI951111XnXTSST1/8rJy5cokNtkG8kxYnlf2I095fqln/M8+++yeH+HE2759e8pzpJvHy9skF0Vt58zL0gbnajuWdEnz4osvTmmWAg3IC2HURW7tjPyXZYAFCxaktNrahDbHvymsC6R97733Vp9++mnqA2W4jBYKOBEZZ2ZVwM2bN6967bXXqjlz5tTCAMvJ+++/37PIPPzww2lQDWGFe/nll5MFL1wM7vv27ev589s06Jfs3r07CYDc7/HHH0/iou2cucWQ/H311Ve9vPzoRz9K/iHgsDCGu+uuu3rnQATleX3yyScn5CGPd+jQoZ5/k2MQIizP69atW3vhMTW5atWqnh95DpHCANbkYmAr24S4tEm/c3ap+34CjnRff/31Xh298847E4QjeQ/3xz/+sZo7d24vLHfl4Mw5H3vssV542Sb0oXC0SZdyBIjuL7/8shdfATf6KOBEZJyZVQHHgB2Co+Saa65J4mDLli09v/379yfBF/sM7FjwyrjLli1LFqQQFlhaWNcW+22QHuR+sX4qP6bpnFjGyB/nCr9YP1emAYgHrGfkFYGW55V0Yh/hiHgJ8VBakRhwmH4u8xNxyeuFF15YC8thuvSbb76Z4Ee7NE37lm1CfnMR3vWcJaXLy0Sd//nPf+7tI7IR22wj3vJ80s4ffvhhLf2XXnqpNjjjNm7c2NuPNmGbNqEPRRhtQtplujlnnHFGtWPHjqIk/78jLhbCJjgPlP7w4IMPVnv37k2/ZRi88cYbjXEjHpRhMNlzEmfQOZviRdymeIPixjlL/0HxIm7bOaN+Ii7bZR8RERkXRkbAYcFhQL388st7ftxgmY6K/SbBBQgm1oXFjfq+++5Lx8X0YhtN6ZXiq+kYQMggEkr/SKMUQ2FxivTzvCIWIq8IOSxPTAsyzVqK0EECrq3cCELSJC6iA2GWh7cJuLJNyA9tEsK13zn7wfk5Z9QDojLCSC+vW/Ic+6WAQ9h1FXCl1S/fx+V9iDZpavcSpqNJp3SIWt3ou7KPiIiMC7Mq4LBaMdjmU17nnntusjJt3rw5DepY4iIMS8/HH3/c228TUwz+k5myKkUL4gTLyWeffdbzazsn08EIzFJgQT8BR14RaGWcJjZt2pTi5dOHkxFwiC1EV+Q1rJ35MWVdBGWbYHmjTSh/v3MOohRTOf0EHISIQyQxvcs0b5nGsAKONplMH8qJ9W+4qaYlIiLSj1kVcMDUHVan2GcQZg3VmjVrqiNHjkyYxiKMdUmx3yamlixZkoRXTDsiVLq8DiTOGcJm+fLlaSqtyzkRMuUDGWGp6ifgyCtTgnleea1KHMdU5KJFi3r7rMnLhUgpxnLaxFQp+hBruPyYsICWaZZtQnmpn3wKtemcgyjFVM4gAQfUAdOh5RRzMKyAo03yKVPapEsfKiE/N9xwgwJORERmlFkXcCz0Z41XuHzqDEsTVq0yLARI7krR8MQTT6QnSnFdH2IAFp/HYnlEwbXXXtv3nHlcjg2LC2mUDzHkx+ZigbzleS1fC8L0Xbh8CjnA4hTuD3/4Q/WDH/ygMa95/eQPMbAGqMwfgpCHMsKFqCzbhIX6EWfQOfvR5CJuPwFHHSP4w1F/r776at90Q8j1E3C0CX0oHG3StQ+JiIjMNrMu4AIG1fnz59f8B4X1gyla4uav3ugCwoF4bdacfiB8iBuv0uhKv7ySJq/SoA7a8kRYaWEaBNa7/KGLJtrqPvzb8jMb0E683411b+QHePkyT+o2WSQnQ6Rb+ouIiIwSR03AiQwL1jKsZvkUPNPNn3zySeuraURERI5FFHAyNrAmjQdbmH7esGFDeloU61v+rjwREZG/BBRwMlYg4h555JHeukWmU88777zacSIiIscyCjgRERGRMUMBJyIiIjJmKOBERERExgwFXAf86LWIiIiMEgq4DijgREREZJRQwHVAASciIiKjhAKuAwo4ERERGSUUcB1QwImIiMgooYDrgAJORERERgkFXAcUcCIiIjJKKOA6oIATERGRUUIB1wEFnIiIiIwSCrgOKOBERERklFDAdUABJyIiIqOEAq4DCjgREREZJRRwHVDAiYiIyCihgOuAAk5ERERGCQVcBxRwIiIiMkoo4Drw0EMPVfPnz6/5i4iIiBwNFHAiIiIiY4YCTkRERGTMUMB1wDVwIiIiMkoo4DqggJPZYN68eTU/mRwnn3xyzU9E5FhCAdcBBdx/VG+//Xb10ksvVWeeeWYtTKbOiSeeWO3fv79atGhRLWy6WbhwYa89y7BBEHe6+8Hxxx+fHhS69dZba2GTgfQee+yx6vLLL6+FiYgcKyjgOjAOAu7zzz+vDh8+3NtfvXp12ifv5bFNMHg+99xzNf9gNgXc7bffXn311VfVgQMHqi+++CKV4+abb05hnP/VV19NfoQdOnSouuKKK3pxiff111+nuN9+++2EOukC7uOPP57gRx3m7uDBg9Vll12WwugXTa5Mtx/btm2rvvnmmyTiwo9t8k95OB/urbfeqsWdDLMp4E477bTq3XffTb9lWDDdAi749NNPq08++aTmLyJyLKCA68BsCThE14033ljz7wICDhdTR8MKOI4bVuzMFAz4+cDLdoiqrVu3JrET5STPr732WtpGJHBsWLGWLl2a9ru+AmbOnDnVl19+WauHvP0RGwiDDz74YMIxhHet6xJE6JtvvjnB784776x2796dysk5EXkIujLuqNNFwM0Ua9eurY4cOZLatQwTERl3FHAdmC0Bh+UpHELi1FNPrR3TBgLuySefrD788MPq7LPPrgm4VatW9dLGqoNAwL/NghTlza1PnCOvByxCnC/2169fn6xfsY+VBtGB45f8lflugjTzdPvBtGNYpubOndsrf3lcF+64445q+fLl1Z49eyZYmMr2j3bK405WwC1Y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/QURi6dL/0EwuBFvMtOV/UCs5oNVGT5KxCDLbxk2iLycZVg/iMdAD5MV9m0gBhjgh31tDYKOsjStmYqwpj7Wpe81xe3S98jLsH2IY4nTVI5RhDrIRR8gkG+44YaeiMeKzUML/MYx0ffKuFjueCKWh2amu2+JyOyggBP5C4X1eFhzurwIWUYPLIOl+MJSV1opm+ChHCyEw4heERktFHAiImMI1lOmQFknyLQtU6GIsn7WShE5dlDAiYiMKbx/L15KzLq7//mf/6kdIyLHJgo4ERERkTHjuO9973s1TxEREREZXY77p3/6p5qniIiIiIwux/31X/91zVNERERERpfj/j9X8xQRERGR0UUBJyIiIjJmJAH3r//6r7UAERERERlNkoD7zne+UwsQERERkdEkCTj4x3/8x1qgiIiIiIwePQHn06giIiIi40FPwPkwg4iIiMjog9FtgoD77ne/WztIREREREaH/6fb/lfAwd///d/XDhQRERGRow86rVHAwT//8z/XIoiIiIjI0QN9lum1uoCDMpKIiIiIHD0KrVYXb+BrRURERERGA3RZJwEHf/VXf1VLQERERERmh+9973tJj5Uara+Ag3//93+vJSYiIiIiM8/f/M3f1LRZJwEHf/d3f1dLUERERERmDvRXqcmGEnCgJU5ERERkdvjbv/3bmhYrqHk0ggmPedjyBCIiIiIyfaC3Sh3WQM2jLz6dKiIiIjIzlLqrDzWPgfi1BhEREZHpg6Vq2VcWulDz6Awncm2ciIiIyOSYhHBL/F/+/cvmMlt1ggAAAABJRU5ErkJggg==>