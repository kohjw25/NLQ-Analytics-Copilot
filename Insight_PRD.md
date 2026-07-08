# Product Requirements Document: Natural-Language-to-Insight Analytics Copilot

## 1. Product Overview

### Product Name

**Insight Copilot**

### One-Liner

A natural-language analytics tool that allows business users to upload tabular datasets, ask questions in plain English, and receive trusted answers, charts, and key insights without needing SQL or BI expertise.

### Problem Statement

Dashboards are useful, but they often require users to know what to look for upfront. Many business users still depend on analysts to write SQL, create charts, and interpret results. This creates bottlenecks, slows decision-making, and limits self-service analytics adoption.

Insight Copilot solves this by allowing users to interact with data conversationally. A user can upload a dataset, ask a question such as “Which customer segment had the highest revenue growth last quarter?”, and receive a validated query output, relevant visualisation, and short insight summary.

## 2. Target Users

### Primary Users

**Business stakeholders / non-technical users**

* Marketing managers
* Commercial managers
* Product managers
* Sales operations teams
* Strategy teams

They understand business questions but may not know SQL, Python, or dashboard-building tools.

### Secondary Users

**Analysts and analytics product owners**

* Data analysts
* BI developers
* Analytics product managers

They benefit from faster ad hoc analysis, reusable query logic, and reduced repetitive reporting requests.

## 3. Goals and Objectives

### Product Goals

1. Enable non-technical users to query uploaded datasets using plain English.
2. Automatically generate accurate tables, charts, and written insights.
3. Reduce dependency on analysts for simple ad hoc analysis.
4. Build trust by showing query logic, assumptions, and validation results.
5. Demonstrate how GenAI can be safely applied to analytics workflows.

### Business / Portfolio Objective

Position the product as a practical GenAI analytics solution that addresses a real PM problem: self-service analytics still breaks down when users do not know SQL, data structure, or the right chart type.

## 4. Success Metrics

### User Success Metrics

* % of user questions successfully answered without analyst intervention
* Average time from question to insight
* User satisfaction score after each answer
* % of generated charts accepted without manual correction
* % of ambiguous questions clarified successfully

### Product Quality Metrics

* Query accuracy score
* Chart relevance score
* Insight usefulness score
* Error rate for failed query execution
* Hallucination rate in generated explanations
* % of answers with clear assumptions displayed

### Adoption Metrics

* Number of datasets uploaded
* Number of natural-language questions asked
* Repeat usage rate
* Average questions per active user
* Saved insights / exported reports per user

## 5. MVP Scope

### In Scope

The MVP will support:

1. **Dataset Upload**

   * Upload CSV or Excel files
   * Preview dataset
   * Detect column names, data types, missing values, and date fields

2. **Natural Language Question Input**

   * User asks questions in plain English
   * Example: “Show revenue trend by month”
   * Example: “Which product category declined the most?”

3. **Query Generation**

   * Convert user question into SQL or pandas code
   * Execute query against uploaded dataset
   * Return resulting table

4. **Auto-Visualisation**

   * Recommend suitable chart type based on query intent and data structure
   * Generate bar charts, line charts, scatter plots, tables, and summary cards
   * Allow user to switch chart type manually

5. **Insight Generation**

   * Generate concise written interpretation of result
   * Highlight trends, outliers, top/bottom performers, and changes over time

6. **Clarification Handling**

   * Ask follow-up questions when user intent is ambiguous
   * Example: “Do you mean revenue by order date or shipment date?”

7. **Trust and Transparency Layer**

   * Show generated query
   * Show assumptions made
   * Show data fields used
   * Flag low-confidence answers

8. **Evaluation Harness**

   * Score generated query correctness
   * Compare generated outputs against expected test cases
   * Track failure types such as wrong aggregation, wrong date filter, wrong column, or invalid chart

### Out of Scope for MVP

* Live database connections
* Enterprise authentication
* Scheduled dashboard refresh
* Multi-file joins
* Advanced forecasting
* Row-level security
* Fully automated executive storytelling
* Production-grade governance workflow

## 6. Key User Journeys

### Journey 1: First-Time Dataset Upload

1. User uploads a CSV or Excel dataset.
2. System previews the first few rows.
3. System detects columns, data types, date fields, numeric fields, and categorical fields.
4. System generates a short dataset summary.
5. User sees suggested starter questions.

### Journey 2: Ask a Plain-English Question

1. User asks: “What were the top 5 products by revenue last month?”
2. System identifies intent: ranking, revenue metric, product dimension, date filter.
3. System maps the question to available columns.
4. System generates and executes query.
5. System returns:

   * Result table
   * Bar chart
   * Key insight summary
   * Query logic and assumptions

### Journey 3: Ambiguous Question

1. User asks: “How did sales perform?”
2. System detects ambiguity.
3. System asks: “Do you want sales performance by month, product, market, or customer segment?”
4. User selects “by month”.
5. System generates monthly sales trend chart and insight summary.

### Journey 4: User Reviews Trust Layer

1. User receives an answer.
2. User expands “How this was calculated”.
3. System shows:

   * Generated query
   * Columns used
   * Aggregation method
   * Filters applied
   * Confidence score
4. User can mark answer as correct, incorrect, or unclear.

## 7. Functional Requirements

### 7.1 Dataset Upload and Profiling

The system should allow users to upload CSV and Excel files.

The system must:

* Validate supported file formats
* Display dataset preview
* Detect column data types
* Identify date, numeric, and categorical fields
* Identify missing values
* Generate a short metadata summary
* Suggest possible metrics and dimensions

Example output:

* Metrics detected: Revenue, Orders, Quantity, Margin
* Dimensions detected: Region, Product Category, Customer Segment
* Date fields detected: Order Date, Ship Date

### 7.2 Natural Language Query Interface

The system should provide a chat-style interface where users can ask business questions.

The system must:

* Accept plain-English questions
* Identify analytical intent
* Map user terms to dataset columns
* Detect missing context
* Ask clarification questions when required
* Maintain conversational context for follow-up questions

Example:
User: “Which region performed best?”
System: “Do you want to measure performance by revenue, orders, margin, or growth?”

### 7.3 Query Generation

The system should translate natural language into executable SQL or pandas logic.

The system must:

* Generate valid query code
* Use only available dataset columns
* Avoid inventing columns or metrics
* Apply correct aggregation logic
* Apply date filters correctly
* Handle basic calculations such as growth rate, share of total, average, and ranking

Supported query types:

* Total / sum
* Average
* Count
* Ranking
* Trend over time
* Group by dimension
* Percentage share
* Period-over-period comparison
* Top / bottom performers

### 7.4 Query Execution

The system should execute generated queries safely against the uploaded dataset.

The system must:

* Run query in a controlled environment
* Return structured results
* Handle query errors gracefully
* Explain why a query failed
* Suggest a corrected question where possible

### 7.5 Auto-Visualisation

The system should recommend and generate the most suitable chart based on the result.

Chart selection logic:

* Time trend → Line chart
* Ranking → Bar chart
* Category comparison → Bar chart
* Share of total → Donut or stacked bar chart
* Correlation → Scatter plot
* Single KPI → Scorecard
* Detailed results → Table

The system must:

* Generate readable charts
* Use clear titles and axis labels
* Avoid misleading chart types
* Display units where available
* Allow users to switch chart type manually

### 7.6 Insight Generation

The system should generate a concise written summary of the result.

The system must:

* Describe the main finding
* Highlight top and bottom performers
* Identify trends and anomalies
* Avoid unsupported claims
* Reference actual numbers from the result
* Clearly state assumptions

Example:
“Revenue increased by 18% from March to April, mainly driven by the Electronics category, which contributed 42% of total growth. The West region underperformed, declining by 9% over the same period.”

### 7.7 Clarification and Ambiguity Handling

The system should detect when a question cannot be answered confidently.

Ambiguity examples:

* “Performance” without a metric
* “Recent” without a date range
* “Best” without a ranking measure
* Multiple possible date columns
* Similar column names

The system should ask targeted clarification questions instead of guessing.

Example:
“Your dataset has both Order Date and Delivery Date. Which one should I use for this analysis?”

### 7.8 Trust and Explainability

The system should make generated answers transparent.

Each answer should include:

* Query used
* Columns used
* Filters applied
* Aggregation method
* Assumptions made
* Confidence level
* Warning if the answer may be unreliable

This is critical because business users need to trust the result before using it for decisions.

### 7.9 Evaluation Harness

The product should include a lightweight evaluation framework to test whether generated queries and outputs are correct.

The evaluation harness should include:

* A set of sample datasets
* A set of benchmark questions
* Expected query outputs
* Scoring logic
* Failure classification

Evaluation dimensions:

1. **Query validity**
   Does the generated query run successfully?

2. **Column mapping accuracy**
   Did the system choose the correct columns?

3. **Aggregation accuracy**
   Did the system use the correct sum, average, count, or calculation?

4. **Filter accuracy**
   Were date ranges and conditions applied correctly?

5. **Result accuracy**
   Does the output match the expected answer?

6. **Chart relevance**
   Was the selected visual appropriate for the question?

7. **Insight faithfulness**
   Does the written insight accurately reflect the query result?

Example test case:

Question:
“Which region had the highest revenue in Q2?”

Expected logic:

* Filter dates to Q2
* Group by Region
* Sum Revenue
* Sort descending
* Return top region

Failure types:

* Used wrong date column
* Forgot Q2 filter
* Counted orders instead of summing revenue
* Sorted ascending instead of descending
* Generated insight that was not supported by result

## 8. Non-Functional Requirements

### Performance

* Dataset upload and profiling should complete within a reasonable time for small to medium datasets.
* Query execution should return results quickly for datasets up to MVP size limits.

### Reliability

* System should fail gracefully when the dataset is unsupported, too large, or poorly structured.
* System should not generate unsupported insights when query execution fails.

### Security

* Uploaded data should be processed securely.
* Data should not be used for model training unless explicitly permitted.
* User-uploaded files should be deleted after session expiry unless saved by the user.

### Usability

* Interface should be simple enough for non-technical users.
* Users should not need to understand SQL or pandas.
* Technical details should be available but not forced into the main experience.

### Trustworthiness

* System should distinguish between calculated facts and inferred interpretations.
* Low-confidence answers should be flagged clearly.
* Assumptions should be visible.

## 9. Example User Stories

### Business User

As a marketing manager, I want to ask “Which campaign drove the most revenue?” so that I can quickly identify the best-performing campaign without waiting for an analyst.

### Product Manager

As a product manager, I want to ask “Where are users dropping off in the funnel?” so that I can identify friction points and prioritise improvements.

### Analyst

As an analyst, I want to inspect the generated query so that I can validate whether the answer is correct before sharing it with stakeholders.

### Analytics Product Owner

As an analytics product owner, I want to track query accuracy and failure types so that I can improve the copilot over time.

## 10. MVP User Interface

### Main Screens

1. **Upload Dataset Screen**

   * Upload file
   * Dataset preview
   * Field summary
   * Suggested questions

2. **Chat-to-Insight Screen**

   * Natural-language input box
   * Answer card
   * Chart visual
   * Result table
   * Insight summary

3. **Trust Panel**

   * Generated query
   * Columns used
   * Filters applied
   * Assumptions
   * Confidence score

4. **Evaluation Dashboard**

   * Query accuracy
   * Failed test cases
   * Common failure types
   * Chart selection accuracy
   * Insight faithfulness score

## 11. Technical Approach

### Core Components

1. **LLM Layer**

   * Interprets user intent
   * Generates SQL or pandas code
   * Generates written insights
   * Handles clarification questions

2. **Data Profiling Layer**

   * Reads uploaded dataset
   * Detects schema
   * Classifies metrics, dimensions, and dates
   * Provides metadata to the LLM

3. **Query Execution Layer**

   * Executes generated SQL or pandas logic
   * Returns structured outputs
   * Handles errors and retries

4. **Visualisation Layer**

   * Uses Plotly or Vega-Lite
   * Selects chart type based on intent and data shape
   * Generates chart config

5. **Evaluation Layer**

   * Runs benchmark questions
   * Compares actual outputs with expected outputs
   * Scores query and insight quality

### Suggested Stack

* Frontend: Streamlit or React
* Backend: Python / FastAPI
* Query engine: DuckDB or pandas
* LLM: OpenAI, Claude, Gemini, or local open-source model
* Charting: Plotly or Vega-Lite
* Evaluation: Python test harness with benchmark datasets
* Storage: Local session storage for MVP

## 12. Key Product Decisions

### Text-to-SQL vs Text-to-Pandas

For MVP, DuckDB with SQL is recommended because SQL is easier to inspect, evaluate, and explain. Pandas can be used later for more advanced transformations.

### Why Show the Query?

Showing the generated query increases trust and allows analysts to validate the answer. This is important because GenAI analytics tools often fail when users cannot see how the answer was calculated.

### Why Include Evaluation Early?

Evaluation should not be treated as an afterthought. The product’s core promise is not just generating charts, but generating correct and trustworthy insights.

## 13. Risks and Mitigations

### Risk 1: Incorrect Query Generation

The LLM may choose the wrong metric, aggregation, or filter.

Mitigation:

* Use schema-aware prompts
* Add validation rules
* Ask clarification questions
* Score outputs through evaluation harness

### Risk 2: Hallucinated Insights

The LLM may generate explanations not supported by the data.

Mitigation:

* Generate insights only from executed query results
* Require numbers in insights to come from result table
* Add faithfulness checks

### Risk 3: Misleading Visualisations

The system may select an inappropriate chart type.

Mitigation:

* Use rule-based chart selection for MVP
* Limit chart types initially
* Score chart relevance during evaluation

### Risk 4: Ambiguous User Intent

Business terms such as “best”, “performance”, or “recent” may be unclear.

Mitigation:

* Detect ambiguity
* Ask targeted clarification questions
* Display assumptions when proceeding

### Risk 5: Poor Dataset Quality

Uploaded datasets may contain missing values, inconsistent date formats, or unclear column names.

Mitigation:

* Run profiling checks
* Warn users about data quality issues
* Suggest column mapping corrections

## 14. Launch Plan

### Phase 1: MVP Prototype

Build a working prototype that supports CSV upload, natural-language questions, SQL generation, chart generation, and insight summaries.

### Phase 2: Evaluation and Trust Layer

Add benchmark datasets, expected answers, scoring logic, failure categorisation, and confidence indicators.

### Phase 3: UX Refinement

Improve clarification flows, chart switching, saved insights, and export options.

### Phase 4: Advanced Analytics

Add support for multi-step analysis, forecasting, anomaly detection, multi-file joins, and dashboard creation.

## 15. Example Demo Flow

1. Upload sample e-commerce dataset.
2. System detects fields: Order Date, Product Category, Region, Revenue, Orders, Customer Segment.
3. User asks: “Which region had the highest revenue growth last quarter?”
4. System asks clarification if multiple date fields exist.
5. System generates SQL query.
6. System returns a ranked bar chart by region.
7. System highlights the top-growing region and growth percentage.
8. User opens trust panel to inspect query and assumptions.
9. Evaluation harness confirms whether the generated query matches expected output.

## 16. Portfolio Narrative

This product solves a common analytics problem: dashboards require users to know SQL, understand the data model, or depend on analysts for every follow-up question. Business users often know the question they want to ask, but they do not know how to translate it into a query or visual.

Insight Copilot bridges that gap by turning plain-English questions into validated queries, charts, and insights. The key product challenge is not only generating an answer, but making that answer trustworthy. That is why the product includes ambiguity handling, explainability, and an evaluation harness from the start.

This demonstrates strong product thinking across GenAI, analytics UX, prompt design, evaluation design, and self-service BI adoption.
