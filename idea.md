# Summarize the File – Design Options

This document outlines possible approaches for implementing a **"Summarize the File"** feature in the chatbot.  
The goal is to improve user experience while working within model context window limitations.

---

## Current Behavior

- Files are uploaded, text is extracted, chunked (~1000 tokens with overlap), and embedded into **pgvector**.  
- Queries go through embedding → vector search → top 5 chunks retrieved → sent to the model with citations.  
- The model is instructed to respond with *“I don’t know”* if the answer is not covered by the context.

### Problem

When a user asks *“summarize the file”*:
- The phrase *“summarize the file”* is embedded and used for retrieval.  
- The system returns **only 5 chunks** related to that phrase.  
- If the file is small (≤ 5 chunks), this may work.  
- If the file is larger, only part of the file is seen by the model, so the summary is incomplete.  

In practice, the model is summarizing the **retrieved context**, not the entire file.

---

## Options

### Option 1: Manual **Summarize File** Button
**Flow**:  
- Add a button in the chat UI.  
- User selects a file from the current session.  
- Run a summarization pipeline across all chunks.

**Pros**
- Explicit, no ambiguity.  
- Reuses existing chunking pipeline.  
- Cacheable results.  

**Cons**
- Extra user step (manual selection).  

---

### Option 2: Auto-Summarize on Upload
**Flow**:  
- Automatically generate a file summary in the background when the file is uploaded.  
- Store summary alongside embeddings.  
- User request for “summarize the file” returns instantly.

**Pros**
- Instant summary response.  
- Summaries available as file previews.  

**Cons**
- Compute cost (summarize files that may never be used).  
- Summaries may become stale if file is updated.  

---

### Option 3: Inline Resolver (No Button)
**Flow**:  
- User types *“summarize the file”*.  
- If only one file in session → summarize it directly.  
- If multiple files exist → present file choices as quick chips.  

**Pros**
- Seamless and natural UX.  
- Minimal UI changes.  

**Cons**
- Requires resolver logic to disambiguate files.  

---

### Option 4: Tiered Summarization
**Flow**:  
- For small files (< X tokens): summarize full text directly.  
- For large files: run **map → reduce** pipeline (summarize chunks, then combine).  

**Pros**
- Efficient.  
- Works for files of all sizes.  

**Cons**
- Slightly slower for large files.  

---

### Option 5: On-Demand Tool Call
**Flow**:  
- Introduce a tool such as `summarize_file(file_id)`.  
- Bot invokes the tool → orchestrates chunking + summarization behind the scenes.  
- Optionally supports follow-up queries on the summary.

**Pros**
- Integrated into chat flow (feels native).  
- Scales to async jobs for very large files.  

**Cons**
- Higher engineering effort.  

---

## Recommendation

| Horizon        | Suggested Approach                                      |
|----------------|----------------------------------------------------------|
| Short term     | **Option 1** (Manual button) + **Option 4** (Tiered summarization) |
| Medium term    | **Option 3** (Inline resolver with file chips)           |
| Long term      | **Option 2** (Auto-summarize on upload) + **Option 5** (Tool call orchestration) |

---

## Next Steps

- Implement summarization pipeline that reuses existing chunks.  
- Add caching for summaries to avoid recomputation.  
- Decide whether to prioritize **explicit control (Option 1)** or **seamless UX (Option 3)** for initial release.  
