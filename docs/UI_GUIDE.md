# Meditation Database - User Interface Guide

This guide covers both the **CLI** and **Web UI** options for ingesting and managing meditation texts.

## Quick Start

```bash
# Install dependencies (including Streamlit)
poetry install

# Option 1: Use the Web UI (Recommended for beginners)
poetry run streamlit run app.py

# Option 2: Use the CLI (Best for batch processing)
poetry run python scripts/ingest.py --help
```

---

## Web UI (Streamlit)

### Starting the Web Interface

```bash
poetry run streamlit run app.py
```

This will open a browser window at `http://localhost:8501`

### Features

The web interface has three main pages:

#### 1. 📥 Ingest New Document

**Upload documents with rich metadata:**

- **Source Type**: Choose URL or File Path
- **Title**: Document name
- **Description**: Human-readable summary
- **Document Type**: ancient_text, scientific_paper, lecture, commentary, modern_teaching
- **Category**: buddhism, neuroscience, psychology, etc.
- **Tags**: Comma-separated keywords

**Example workflow:**
1. Select "URL" or "File Path"
2. Enter source (e.g., `https://suttacentral.net/...` or `Books/sutra.pdf`)
3. Fill in metadata fields
4. Click "Start Ingestion"
5. Watch real-time progress
6. View detailed pipeline results

#### 2. 📚 Browse Database

**Explore your meditation library:**

- Filter by status (COMPLETED, FAILED, PENDING, etc.)
- Filter by document type
- Filter by category
- View document metadata, tags, and descriptions
- Preview chunk content
- See chunk counts and creation dates

#### 3. 📊 Statistics

**Visualize your database:**

- Total documents and chunks
- Status distribution (bar chart)
- Document type breakdown
- Category distribution
- Recent documents timeline

### Pros of Web UI

✅ Visual feedback on ingestion progress
✅ Easy metadata input with dropdowns
✅ Database exploration with filters
✅ No need to remember CLI flags
✅ Real-time status updates
✅ Great for exploratory work
✅ Accessible to non-technical users

### Cons of Web UI

❌ Requires running a server
❌ Not ideal for batch processing
❌ Can't easily automate
❌ One document at a time

---

## CLI (Command Line Interface)

### Basic Usage

```bash
# Ingest from URL
python scripts/ingest.py "https://example.com/article"

# Ingest PDF with metadata
python scripts/ingest.py "Books/sutra.pdf" \
  --title "Diamond Sutra" \
  --description "Ancient Mahayana Buddhist text on emptiness" \
  --type ancient_text \
  --category buddhism \
  --tags mahayana wisdom prajna

# Resume failed ingestion
python scripts/ingest.py --resume 123

# List all documents
python scripts/ingest.py --list

# Batch ingest multiple sources
python scripts/ingest.py url1 url2 path/to/file.pdf
```

### Enhanced CLI with Metadata (Future)

After updating the CLI script, you'll be able to use:

```bash
python scripts/ingest.py <source> \
  --title "Document Title" \
  --description "Brief description" \
  --type [ancient_text|scientific_paper|lecture|commentary|modern_teaching] \
  --category "buddhism" \
  --tags tag1 tag2 tag3
```

### CLI Options

| Flag | Description | Example |
|------|-------------|---------|
| `--title`, `-t` | Document title | `--title "Heart Sutra"` |
| `--description`, `-d` | Description | `--description "Core text on emptiness"` |
| `--type` | Document type | `--type ancient_text` |
| `--category`, `-c` | Primary category | `--category buddhism` |
| `--tags` | Space-separated tags | `--tags zen koans wisdom` |
| `--resume`, `-r` | Resume by ID | `--resume 5` |
| `--list`, `-l` | List all documents | `--list` |
| `--quiet`, `-q` | Minimal output | `--quiet` |
| `--verbose`, `-v` | Detailed logging | `--verbose` |

### Pros of CLI

✅ Perfect for scripting and automation
✅ Batch processing multiple files
✅ No server overhead
✅ Fast for power users
✅ Easy to integrate with CI/CD
✅ Can be called from other scripts

### Cons of CLI

❌ Less user-friendly for beginners
❌ Need to remember command syntax
❌ No visual feedback
❌ Harder to explore database

---

## Recommended Workflows

### For Initial Setup & Exploration

**Use Web UI:**
1. Start Streamlit: `streamlit run app.py`
2. Ingest a few test documents
3. Explore the database visually
4. Understand the metadata structure
5. Check statistics and chunk previews

### For Production Ingestion

**Use CLI:**
1. Create a script with all your sources
2. Use batch ingestion for multiple files
3. Automate with cron jobs or GitHub Actions
4. Use `--quiet` mode for logs

### Hybrid Approach (Best of Both)

1. **Initial ingestion**: Use CLI for batch processing
   ```bash
   python scripts/ingest.py Books/*.pdf --type ancient_text --category buddhism
   ```

2. **Verify results**: Open Web UI to check status
   ```bash
   streamlit run app.py
   ```

3. **Fix failures**: Use Web UI to re-ingest failed documents with adjusted metadata

4. **Ongoing maintenance**: Use CLI for scheduled ingestion, Web UI for exploration

---

## Example Use Cases

### Use Case 1: Ingesting Ancient Buddhist Texts

**CLI (batch):**
```bash
python scripts/ingest.py \
  "Books/Digha_Nikaya.pdf" \
  "Books/Majjhima_Nikaya.pdf" \
  "Books/Samyutta_Nikaya.pdf" \
  --type ancient_text \
  --category buddhism \
  --tags "pali-canon" "theravada" "sutta"
```

**Web UI (interactive):**
1. Upload each PDF via file path
2. Add rich descriptions for each text
3. Preview first few chunks to verify quality
4. Use filters to view all Pali Canon texts

### Use Case 2: Adding Scientific Papers

**CLI:**
```bash
python scripts/ingest.py \
  "Papers/meditation_fmri_study.pdf" \
  --title "Neural Correlates of Mindfulness" \
  --description "fMRI study showing brain changes during meditation" \
  --type scientific_paper \
  --category neuroscience \
  --tags mindfulness fmri brain-imaging 2024
```

**Web UI:**
1. Navigate to "Ingest New Document"
2. Select "File Path" → `Papers/meditation_fmri_study.pdf`
3. Fill form with metadata
4. Watch real-time pipeline progress
5. Check "Browse Database" → Filter by type: "scientific_paper"

### Use Case 3: Adding Lectures from URLs

**CLI:**
```bash
python scripts/ingest.py \
  "https://youtube.com/transcript/abc123" \
  --title "Jon Kabat-Zinn on MBSR" \
  --description "Introduction to Mindfulness-Based Stress Reduction" \
  --type lecture \
  --category psychology \
  --tags mbsr mindfulness modern-teaching
```

**Web UI:**
1. Select "URL" source type
2. Paste lecture transcript URL
3. Add metadata via form
4. View statistics page to see lecture count

---

## Troubleshooting

### Web UI won't start

```bash
# Make sure Streamlit is installed
poetry install

# Check if port 8501 is already in use
lsof -i :8501

# Use a different port
streamlit run app.py --server.port 8502
```

### CLI commands fail

```bash
# Make sure you're in the project root
pwd  # Should show .../meditation-assistant

# Check environment variables are set
cat .env

# Run with verbose logging
python scripts/ingest.py <source> --verbose
```

### Database connection errors

```bash
# Start Docker PostgreSQL
docker compose -f docker/docker-compose.dev.yml up db -d

# Verify connection string in .env
echo $DB_URL

# Test connection
poetry run python -c "from db.database import session_scope; \
  with session_scope() as s: print('Connected!')"
```

---

## Tips & Best Practices

### Metadata Strategy

1. **Be consistent**: Use the same category names (lowercase, no spaces)
2. **Use tags liberally**: They're searchable and flexible
3. **Write good descriptions**: Future you will thank present you
4. **Document types are important**: They help organize query patterns

### Performance Tips

1. **Batch processing**: CLI is faster for multiple documents
2. **Monitor failures**: Check Web UI statistics page regularly
3. **Resume failed jobs**: Use `--resume <id>` instead of re-ingesting
4. **Clear old chunks**: Failed ingestions leave orphaned chunks

### Organization Tips

1. **Create a spreadsheet**: Track what you've ingested
2. **Use consistent naming**: `tradition_text_name.pdf`
3. **Tag by era**: ancient, modern, contemporary
4. **Tag by practice**: mindfulness, insight, concentration

---

## Next Steps

1. **Install Streamlit**: `poetry install`
2. **Try the Web UI**: `streamlit run app.py`
3. **Test with one document**: Use a small PDF or URL
4. **Explore the database**: Check statistics and browse
5. **Scale up**: Use CLI for batch ingestion

For more details, see:
- [CLAUDE.md](../CLAUDE.md) - Architecture overview
- [README.md](../README.md) - Project documentation
- [scripts/ingest.py](../scripts/ingest.py) - CLI implementation
- [app.py](../app.py) - Web UI implementation
