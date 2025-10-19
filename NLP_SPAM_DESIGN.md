# NLP-Enhanced Spam Detection Design

## Architecture: Hybrid Keyword + NLP System

### Current System (Baseline - Keep It!)
- ✅ Fast keyword matching (regex-based)
- ✅ Works for 90% of cases
- ✅ Zero latency, no dependencies
- ✅ Handles financial spam, military fundraising exceptions

### NLP Enhancement Layer (Add On Top)
- Only runs when keyword system is uncertain
- Provides semantic understanding
- Catches edge cases that keywords miss

---

## Two-Stage Detection Flow

```
Message Received
    ↓
[Stage 1: Keyword Filter] ← Current system
    ↓
    ├─→ Clear spam? → FILTER (fast path, 70% of cases)
    ├─→ Clear legitimate? → KEEP (fast path, 25% of cases)
    └─→ Uncertain? → Go to Stage 2 (5% of cases)

[Stage 2: NLP Analysis] ← New enhancement
    ↓
    ├─→ Language Detection (FastText)
    ├─→ Named Entity Recognition (spaCy per language)
    ├─→ Semantic Topic Classification
    └─→ Final decision
```

---

## Implementation Plan

### 1. Language Detection (FastText)
**Library**: `fast-langdetect` (80x faster, 95% accuracy)

**Purpose**: Identify Ukrainian, Russian, or English text

**Usage**:
```python
from fast_langdetect import detect_language

lang = detect_language(text)
# Returns: 'uk', 'ru', 'en', or None
```

**Benefits**:
- Ultra-fast (<1ms)
- Supports Ukrainian, Russian, English
- No model download needed
- Works on short text (Telegram messages)

---

### 2. Named Entity Recognition (spaCy)
**Models**:
- Ukrainian: `xx_ent_wiki_sm` (multilingual) or community Ukrainian model
- Russian: `ru_core_news_sm`
- English: `en_core_web_sm`

**Purpose**: Extract locations, organizations, people

**Example**:
```python
import spacy

nlp_uk = spacy.load("xx_ent_wiki_sm")  # Multilingual
doc = nlp_uk("Ізраїль атакував Газу")

for ent in doc.ents:
    print(f"{ent.text} → {ent.label_}")
# Output: Ізраїль → LOC, Газу → LOC
```

**Use Cases**:
1. **Location-based filtering**:
   - If mentions Israel, Gaza, Tehran → Check if also mentions Kyiv, Moscow
   - If only Middle East locations → OFF-TOPIC

2. **Organization detection**:
   - Detects: ЗСУ, Азов, Вагнер, Hamas, Hezbollah
   - Cross-reference with whitelist

3. **Person detection**:
   - Putin, Zelensky → WAR-RELATED
   - Netanyahu, Khamenei → OFF-TOPIC (unless also mentions Ukraine/Russia)

---

### 3. Semantic Topic Classification
**Approach**: Compare message embedding to reference texts

**Reference Texts**:
- **War-related**: "Ukrainian forces attack Russian positions near Bakhmut"
- **Financial spam**: "Support my channel, donate to card number"
- **Off-topic**: "Israel strikes Gaza, Hamas responds"

**Method**:
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

# Compute similarity
msg_embedding = model.encode(message)
war_similarity = cosine_similarity(msg_embedding, war_reference)
spam_similarity = cosine_similarity(msg_embedding, spam_reference)

# Decision
if war_similarity > 0.7:
    return "ON-TOPIC"
elif spam_similarity > 0.6:
    return "SPAM"
```

**Benefits**:
- Works across languages (multilingual embeddings)
- Captures semantic meaning, not just keywords
- Handles paraphrasing and synonyms

**Downsides**:
- Requires ~500MB model
- Slower (~50-100ms per message)

---

## Hybrid Decision Logic

### Current Keyword System
```python
# Stage 1: Fast keyword check
is_spam, reason = keyword_spam_filter(text)

if is_spam and confidence > 0.9:
    return FILTER, reason  # High confidence spam
elif not is_spam and confidence > 0.9:
    return KEEP, reason    # High confidence legitimate
else:
    # Low confidence, use NLP
    return nlp_enhanced_check(text)
```

### NLP Enhancement (Only for Uncertain Cases)
```python
def nlp_enhanced_check(text):
    # 1. Detect language
    lang = detect_language(text)

    # 2. Load appropriate spaCy model
    nlp = get_model_for_language(lang)
    doc = nlp(text)

    # 3. Extract entities
    locations = [ent.text for ent in doc.ents if ent.label_ == "LOC"]
    orgs = [ent.text for ent in doc.ents if ent.label_ == "ORG"]

    # 4. Location-based decision
    ukraine_russia_locations = ["Ukraine", "Russia", "Kyiv", "Moscow", "Україна", "Росія"]
    off_topic_locations = ["Israel", "Gaza", "Iran", "Syria", "Ізраїль", "Газа"]

    has_war_location = any(loc in locations for loc in ukraine_russia_locations)
    has_off_topic_location = any(loc in locations for loc in off_topic_locations)

    if has_war_location:
        return KEEP, "NLP: Ukraine/Russia location detected"
    elif has_off_topic_location and not has_war_location:
        return FILTER, f"NLP: Off-topic location only: {locations}"

    # 5. Semantic similarity (if still uncertain)
    topic_score = classify_topic(text)
    if topic_score['war'] > 0.7:
        return KEEP, f"NLP: War-related topic (score: {topic_score['war']:.2f})"
    elif topic_score['off-topic'] > 0.6:
        return FILTER, f"NLP: Off-topic content (score: {topic_score['off-topic']:.2f})"

    # 6. Default to KEEP (avoid over-filtering)
    return KEEP, "NLP: Uncertain, defaulting to keep"
```

---

## Performance Considerations

### Model Sizes
- **fast-langdetect**: ~1MB (minimal)
- **spaCy small models**: ~15-50MB each
- **Sentence transformers**: ~500MB (optional, for semantic similarity)

### Speed
- **Keyword matching**: <1ms (current system)
- **Language detection**: <1ms
- **spaCy NER**: 10-50ms
- **Semantic similarity**: 50-100ms

### Optimization Strategy
1. **Cache NLP models** (load once at startup)
2. **Only use NLP for uncertain cases** (~5% of messages)
3. **Lazy load sentence transformers** (only if needed)

---

## Dependencies

```txt
# requirements.txt additions
fast-langdetect==0.2.3       # Fast language detection
spacy==3.7.2                  # NLP framework
# spaCy models (download separately):
# python -m spacy download xx_ent_wiki_sm  # Multilingual
# python -m spacy download ru_core_news_sm # Russian
# python -m spacy download en_core_web_sm  # English

# Optional (for semantic similarity):
sentence-transformers==2.3.1  # Only if using semantic classification
```

---

## Testing Strategy

### Test Cases for NLP Enhancement

**1. Edge Cases Keywords Miss:**
```python
# Paraphrased financial spam
"Please help support our work with a small contribution to 5168 7521 4428 8613"
→ Keywords might miss "contribution" (not in donation keywords)
→ NLP detects financial context

# Off-topic with war terminology
"Israel's army launches offensive in Gaza strip"
→ Contains "army", "offensive" (war keywords)
→ NLP detects Israel/Gaza locations → OFF-TOPIC
```

**2. Multilingual Mixing:**
```python
# Mixed Ukrainian + English
"Підтримка Ukraine forces with donation card 5168..."
→ Keywords work, but NLP can validate language consistency

# Russian message about Israel
"Израиль атаковал Газу, есть жертвы"
→ Keywords: "атаковал" might match attack patterns
→ NLP: Detects Russian language + Israel/Gaza locations → OFF-TOPIC
```

**3. Military Fundraising (Should KEEP):**
```python
"3-тя бригада збирає на Mavic дрони. Карта: 5168..."
→ Keywords: Detects "бригада" + "дрони" → KEEP
→ NLP: Confirms ORG entity (brigade) + equipment context → KEEP
```

---

## Rollout Plan

### Phase 1: Language Detection Only (Week 1)
- Add fast-langdetect
- Log detected languages
- Validate accuracy on real data
- No filtering changes yet

### Phase 2: NER for Locations (Week 2)
- Add spaCy models
- Extract location entities
- Compare with keyword results
- Log discrepancies

### Phase 3: Hybrid Decision Logic (Week 3)
- Implement two-stage filtering
- Use NLP only for uncertain cases
- A/B test against keyword-only

### Phase 4: Semantic Similarity (Optional, Week 4+)
- Add sentence transformers if needed
- Evaluate if extra accuracy is worth the cost
- Tune thresholds based on false positive rate

---

## Success Metrics

### Accuracy Improvements
- **Baseline**: Current keyword system (measure false positive/negative rate)
- **Target**: 10-20% improvement in edge case detection
- **Acceptable Trade-off**: <50ms latency increase for uncertain cases

### Monitoring
```sql
-- Track NLP usage
SELECT
    COUNT(*) as total_messages,
    SUM(CASE WHEN nlp_used = 1 THEN 1 ELSE 0 END) as nlp_analyzed,
    SUM(CASE WHEN nlp_used = 1 AND spam_filtered = 1 THEN 1 ELSE 0 END) as nlp_caught_spam
FROM messages_processed;

-- Compare keyword vs NLP decisions
SELECT
    keyword_decision,
    nlp_decision,
    COUNT(*) as count
FROM spam_filter_log
WHERE nlp_used = 1
GROUP BY keyword_decision, nlp_decision;
```

---

## Alternative: Simpler NLP (If Performance Critical)

If sentence transformers are too heavy, use **lightweight NER only**:

```python
def simple_nlp_check(text):
    """Lightweight NLP using only language detection + NER."""
    # 1. Detect language
    lang = detect_language(text)

    # 2. Load appropriate model
    nlp = get_spacy_model(lang)
    doc = nlp(text)

    # 3. Simple location check
    locations = [ent.text.lower() for ent in doc.ents if ent.label_ == "LOC"]

    war_locs = {"ukraine", "russia", "kyiv", "moscow", "україна", "росія", "київ", "москва"}
    off_topic_locs = {"israel", "gaza", "iran", "syria", "ізраїль", "газа", "іран", "сирія"}

    has_war = any(loc in war_locs for loc in locations)
    has_off_topic = any(loc in off_topic_locs for loc in locations)

    if has_war:
        return KEEP, "Ukraine/Russia location"
    elif has_off_topic and not has_war:
        return FILTER, f"Off-topic: {locations}"

    return UNCERTAIN, "Need human review"
```

**Pros**: Fast (~20ms), small models (~50MB total)
**Cons**: Less sophisticated than semantic similarity

---

## Questions to Decide

1. **Model size budget**: Is 500MB acceptable for sentence transformers, or stick to lightweight NER?
2. **Latency tolerance**: Is 50-100ms acceptable for 5% of messages?
3. **Training data**: Do you want to fine-tune on your actual spam examples later?

Let me know which approach you prefer!
