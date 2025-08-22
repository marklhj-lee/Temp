# Summarize the File – Design Options

This document explores several approaches for implementing a **"Summarize the File"** feature in our chatbot.  
The goal is to balance **user experience**, **technical feasibility**, and **compute cost**.

---

## Background

- Current system:  
  - Files uploaded → extracted → chunked into ~1000 tokens with overlap → embedded into pgvector.  
  - Queries run through vector search → top 5 chunks per file → used as context for model.  
  - Model is instructed to say *“I don’t know”* when answer not in context.

- Problem:  
  - Users often ask for **“summarize the file”**, but full files cannot fit into the model’s context window.  
  - We need a dedicated summarization path that works across the entire file, not just 5 chunks.

---

## Options

### **Option 1: Manual “Summarize File” Button**
- **Flow**: Add a button → user selects file(s) from current session → run summarization pipeline.  
- **Implementation**:  
  - Reuse existing chunks.  
  - Map (summarize each chunk) → Reduce (combine into whole-file summary).  
  - Cache result for re-use.  
- ✅ Pros: Simple, explicit, zero ambiguity.  
- ❌ Cons: Slightly manual UX (extra click).

---

### **Option 2: Auto-Summarize on Upload**
- **Flow**: Every file is summarized in the background at upload time.  
- **Implementation**: Store summary alongside embeddings.  
- ✅ Pros: Instant summaries when requested.  
- ✅ Pros: Doubles as a preview of the file.  
- ❌ Cons: Higher compute cost (many files may never be summarized).  
- ❌ Cons: Summaries may become stale if file changes.

---

### **Option 3: Inline Resolver (No Button)**
- **Flow**: User types *“summarize the file”*.  
- **Implementation**:  
  - If only one file in session → summarize directly.  
  - If multiple → show quick file chips (e.g., “Summarize Q2_Report.pdf / Budget.xlsx”).  
- ✅ Pros: Seamless, feels natural in chat.  
- ✅ Pros: Minimal UI.  
- ❌ Cons: Requires resolver logic to guess intended file.

---

### **Option 4: Tiered Summarization (Small vs. Large Files)**
- **Flow**: Handle small vs. large files differently.  
- **Implementation**:  
  - If file < X tokens → summarize full text directly.  
  - If file > X → use chunk → summarize chunks → reduce.  
- ✅ Pros: Efficient, always works regardless of file size.  
- ✅ Pros: Keeps compute bounded.  
- ❌ Cons: Multi-step summarization adds slight latency for large files.

---

### **Option 5: On-Demand Extended Context (Tool Call)**
- **Flow**: Introduce a tool `summarize_file(file_id)`.  
- **Implementation**:  
  - Bot calls tool → orchestrates chunking + map-reduce summarization.  
  - Optionally allow follow-up queries on summary (“expand section 3”).  
- ✅ Pros: Seamless integration, feels like native ability.  
- ✅ Pros: Scales later (async jobs for very large files).  
- ❌ Cons: More engineering effort up front.

---

## Recommendation

- **Short term (safe & explicit):**  
  Option 1 (Manual button) + Option 4 (Tiered summarization).  

- **Medium term (better UX):**  
  Option 3 (Inline resolver with file chips).  

- **Long term (magic feel):**  
  Option 2 (Auto-summarize on upload) + Option 5 (Tool-based orchestration).  

---

## Next Steps

- Decide whether to prioritize **control** (Option 1) or **seamless UX** (Option 3).  
- Implement chunk-reuse summarization pipeline (map-reduce style).  
- Add caching to avoid recomputing summaries for unchanged files.
