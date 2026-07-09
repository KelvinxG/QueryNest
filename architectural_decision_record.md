# Architectural Decision Record (ADR): GraphRAG Document Chatbot

## 1. Context and Problem Statement
Our organization requires an internal AI chatbot embedded within major messaging platforms (starting with Slack). The chatbot must answer complex, contextual queries based on interconnected documentation hosted on Google Drive (Google Sheets and Google Slides). 

Traditional Vector-based Retrieval-Augmented Generation (RAG) fails in this scenario because it evaluates text chunks in isolation. It cannot comprehend explicit categories, document hierarchies, or cross-format relationships (e.g., how a row in a financial Google Sheet correlates to a strategy point in a Google Slide). 

We need a system that preserves and traverses these relationships while remaining cost-effective under tight AI API token budgets.

## 2. Proposed Architecture Overview
We will implement a **GraphRAG** pipeline built natively in Python. The system splits into three decoupled layers: data ingestion/extraction, a graph database layer, and an asynchronous API layer to handle chat interfaces.

## 3. Decision Drivers
* **Cost Efficiency:** The solution must minimize LLM token usage during prototyping to stay within a standard $10/month budget.
* **Speed to Prototype:** The foundation must be deployable and testable within a single working day.
* **Maintainability:** Written in modular, strongly-typed Python utilizing industry-standard frameworks.

## 4. Component Technical Stack
* **Language/Framework:** Python 3.11+ with **FastAPI** for low-overhead, high-performance asynchronous networking.
* **AI Orchestration:** **LangChain** or **LlamaIndex** to handle abstraction over LLM calls, prompts, and structured output parsing.
* **Graph Storage:** **Neo4j AuraDB (Free Tier)**. Graph databases natively map the `(Document)-[:BELONGS_TO]->(Category)` nodes and edges required for multi-hop relational queries.
* **LLM Engine:** **OpenAI GPT-4o-mini** (for low-cost relationship extraction) and **GPT-4o** (for final reasoning and chat response).
* **Data Sources:** Official **Google API Python Clients** (`google-api-python-client`) reading live cloud payloads via a Google Service Account.

## 5. Key Design Implementations & Constraints

### 5.1 Token Conservation Strategy
* **Strict Localized Testing:** Ingestion testing *must* be executed using miniature mock documents (e.g., a 5-row Sheet, a 3-slide presentation) to prevent token exhaustion.
* **Cached Graph Lookups:** The chatbot will first execute deterministic Cypher queries in Neo4j to build a dense local context string. The LLM is only called once for the final conversational synthesis, avoiding expensive iterative vector scans.

### 5.2 Asynchronous Chat Handling
* Slack and Microsoft Teams require webhooks to respond within **3.0 seconds**, or they trigger timeout retry loops. 
* FastAPI's `BackgroundTasks` will decouple the initial HTTP acknowledgement (`200 OK`) from the heavier Graph query and LLM execution. The final response will be pushed to the platform via an asynchronous POST request to the platform's chat API.

## 6. Consequences
* **Pros:** Highly accurate contextual retrieval; maps real-world data hierarchies; low ongoing operations cost using free-tier databases.