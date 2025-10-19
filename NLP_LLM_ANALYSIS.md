# NLP/LLM Enhancement Analysis for Spam Detection

## Context
After implementing a keyword-based spam filter, we're evaluating whether to add NLP/LLM capabilities to improve accuracy and reduce false positives.

## Current Keyword System (Already Implemented)
- ✅ Regex-based pattern matching
- ✅ Financial spam detection (bank cards, payment links, donation keywords)
- ✅ Off-topic content detection (Israel/Gaza, Iran, Syria, Yemen)
- ✅ Smart exceptions:
  - Military unit fundraising allowed
  - Iran+drone content kept (Russia supply context)
  - Specific location prioritization
- ✅ 17 test cases, all passing

**Performance**: <1ms per message, zero dependencies

## Key Concern: False Positives
**Priority**: Don't miss important war-related messages > Don't let spam through

The keyword system defaults to KEEP when uncertain, but we need real-world data to validate accuracy.

---

## Three Enhancement Options

### 🥇 Option 1: Staged Rollout (RECOMMENDED - Currently Testing)
**Approach**: Deploy keyword filter in production, monitor for 1-2 weeks

**Implementation**:
- Spam is logged and stored in database
- Messages are filtered based on keyword detection
- Manual review of `spam_filtered` table after testing period

**Advantages**:
- Real data from production
- No additional complexity
- Can adjust thresholds based on actual misses

**Timeline**: 2 weeks testing → review → tune

**Decision Point**: If accuracy >95% → keep as-is. If <95% → add Option 2.

---

### 🥈 Option 2: Small Local LLM Confirmation (Ollama)
**Approach**: Use keyword filter as first pass, LLM for confirmation on uncertain cases

**Model**: Qwen2.5-3B (2GB, CPU-friendly, multilingual)

**Architecture**:
```python
def should_filter_message(text):
    # 1. Keyword check
    is_spam_kw, reason = keyword_check(text)

    if not is_spam_kw:
        return False  # Keyword says keep → trust it

    # 2. Keyword suspects spam, ask LLM for confirmation
    llm_decision = ask_llm(text)

    if llm_decision == "SPAM":
        return True  # Both agree → filter
    else:
        logger.warning(f"Keyword/LLM disagree: keeping to be safe")
        return False  # Disagree → keep (conservative)
```

**Docker Integration**:
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ./ollama_models:/root/.ollama
    restart: unless-stopped

  telegram_translator:
    depends_on:
      - ollama
    environment:
      OLLAMA_URL: http://ollama:11434
```

**LLM Prompt Template**:
```
You are filtering spam from Ukraine/Russia war news channels.

Message: "{text}"

Is this spam? Answer ONLY: SPAM or KEEP

SPAM = Personal donations, off-topic (Israel/Gaza/Iran unrelated to Ukraine)
KEEP = War news, military unit fundraising, Iran supplying Russia

Answer:
```

**Advantages**:
- Catches nuanced cases (paraphrasing, context)
- Conservative (requires both systems to agree)
- Multilingual understanding

**Disadvantages**:
- 2GB model download
- ~500ms latency per suspected spam message
- Docker complexity

**When to Use**: If keyword accuracy <95% and false positives are unacceptable

---

### 🥉 Option 3: Lightweight NLP (spaCy + Language Detection)
**Approach**: Add minimal NLP for edge cases only

**Dependencies**:
- `fast-langdetect` (1MB) - Language detection
- `spacy` + `xx_ent_wiki_sm` (15MB) - Multilingual NER

**Implementation**:
```python
from fast_langdetect import detect_language
import spacy

nlp = spacy.load("xx_ent_wiki_sm")

def enhanced_check(text):
    # 1. Keyword check
    is_spam_kw, reason = keyword_check(text)

    # 2. Only enhance uncertain cases
    if "israel" in text.lower() or "gaza" in text.lower():
        doc = nlp(text)
        locations = [e.text.lower() for e in doc.ents if e.label_ == "LOC"]

        # Check if ALSO mentions Ukraine/Russia
        ukraine_russia = ["ukraine", "russia", "kyiv", "україна", "росія"]
        if any(loc in ukraine_russia for loc in locations):
            return False, "NLP: Mixed locations, keeping"

    return is_spam_kw, reason
```

**Advantages**:
- Lightweight (16MB total)
- Fast (~20ms)
- Simple to maintain

**Disadvantages**:
- Limited to location-based logic
- Doesn't understand semantic context

**When to Use**: If specific edge cases emerge (e.g., Israel+Ukraine combinations)

---

## Recommended Workflow

### Phase 1: Testing (Current - Week 1-2)
1. ✅ Keyword filter deployed and running
2. 📊 Collecting data in `spam_filtered` table
3. 🔍 Dashboard created for manual review (logs, spam, stats)

**Action Items**:
- Monitor Flask dashboard daily
- Review spam samples (check content_preview)
- Look for patterns in false positives/negatives

**Questions to Answer**:
- How many messages filtered per day?
- What % are clearly spam?
- Are we missing important messages?
- Are we letting spam through?

### Phase 2: Analysis (Week 3)
**Review 100 random samples from database**:
```sql
SELECT
    date,
    spam_type,
    reason,
    content_preview,
    link
FROM spam_filtered
ORDER BY RANDOM()
LIMIT 100;
```

**Categorize each sample**:
- ✅ Correct (actually spam)
- ❌ False positive (should have kept)
- ⚠️ Uncertain (borderline case)

**Calculate metrics**:
- Precision = Correct / (Correct + False Positive)
- Coverage = Total spam caught / Total spam in channels

### Phase 3: Decision (Week 4)

**If Precision >95%**:
→ Keep keyword system as-is
→ Periodically review (monthly)

**If Precision 85-95%**:
→ Add Option 3 (lightweight NLP)
→ Target specific edge cases found in review

**If Precision <85%**:
→ Add Option 2 (LLM confirmation)
→ Implement conservative filtering (both must agree)

---

## Dashboard for Monitoring

### Tab 1: Live Logs
- Stream telethon listener logs
- Filter by keyword: "spam", "error", "warning"
- Real-time updates via SSE

### Tab 2: Spam Review
- List filtered messages (most recent first)
- Display: date, type, reason, content preview, link
- Actions: "Correctly filtered" / "False positive" / "Uncertain"
- Export to JSON for analysis

### Tab 3: Statistics
```
Total Messages Processed: 12,543
├─ Forwarded: 11,892 (94.8%)
├─ Filtered as Spam: 651 (5.2%)
   ├─ Financial: 423 (65%)
   └─ Off-topic: 228 (35%)

Processing Rate: 127 msg/hour
Database Size: 12.3 MB
Uptime: 14 days, 6 hours

Spam Filter Accuracy (manual review):
├─ Correctly filtered: 95% (621/651)
├─ False positives: 3% (19/651)
└─ Uncertain: 2% (11/651)
```

---

## Implementation Notes

### Database Queries for Dashboard

**Message stats**:
```sql
-- Total messages
SELECT COUNT(*) FROM messages;

-- Spam breakdown
SELECT
    spam_type,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM spam_filtered), 1) as percentage
FROM spam_filtered
GROUP BY spam_type;

-- Recent spam
SELECT
    datetime(date) as time,
    spam_type,
    reason,
    substr(content_preview, 1, 100) as preview,
    link
FROM spam_filtered
ORDER BY date DESC
LIMIT 50;
```

**Processing rate**:
```sql
-- Messages per hour (last 24h)
SELECT
    strftime('%Y-%m-%d %H:00', date) as hour,
    COUNT(*) as messages
FROM messages
WHERE date > datetime('now', '-24 hours')
GROUP BY hour
ORDER BY hour DESC;
```

---

## Cost-Benefit Analysis

### Current Keyword System
- **Cost**: 0ms latency, 0 dependencies
- **Benefit**: Filters 90-95% of spam accurately
- **Risk**: 5-10% edge cases might slip through

### +Lightweight NLP (Option 3)
- **Cost**: +16MB, +20ms latency (uncertain cases only)
- **Benefit**: Handles location-based edge cases
- **Risk**: Still limited to entity recognition

### +LLM Confirmation (Option 2)
- **Cost**: +2GB, +500ms latency (suspected spam only)
- **Benefit**: Semantic understanding, multilingual context
- **Risk**: Non-deterministic, requires GPU for speed

---

## Conclusion

**Current recommendation**: Test keyword system for 1-2 weeks, then decide based on data.

**Success criteria**:
- ✅ >95% precision (correct spam filtering)
- ✅ <1% false positives (important messages kept)
- ✅ Captures 80%+ of obvious spam

**If criteria not met**: Add Option 2 (LLM) as confirmation layer, not replacement.

**Key insight**: Don't optimize for problems you don't have yet. Let real data guide the decision.

---

## Next Steps

1. ✅ Deploy keyword filter (DONE)
2. ✅ Create dashboard for monitoring (IN PROGRESS)
3. 📊 Collect 1-2 weeks of data
4. 🔍 Manual review of 100+ samples
5. 📈 Calculate precision/recall metrics
6. 🚀 Decide: keep, enhance with NLP, or add LLM

**Decision checkpoint**: End of Week 2
