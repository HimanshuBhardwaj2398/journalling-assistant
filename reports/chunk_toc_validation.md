# Chunk + TOC Integrity Audit Report

- Generated: 2026-02-27 04:49:14 UTC
- Sample size requested: 5
- Chunk samples per document: 3
- Embedding consistency check: disabled
- Seed: 42

## Global Summary

- Documents analyzed: 5
- Document verdicts: PASS=1, WARN=4, FAIL=0
- Total checks: 95
- Check outcomes: PASS=91, WARN=4, FAIL=0

## Document [17] Meditation experience is associated with differences in default mode network activity and connectivity

- Status: `completed`
- Final verdict: **PASS**
- Chunk stats: count=17, chars(min/avg/max)=665/2256.5/6773, words(min/avg/max)=91/319.5/894
- Reconstruction: similarity=1.000000 (PASS)
- Headers: markdown_paths=19, toc_paths=19, toc_entries=19
- Check outcomes: PASS=19, WARN=0, FAIL=0

### Missing Markdown Headers In TOC

- None

### Extra TOC Paths Not In Markdown

- None

### Chunk Paths Unmatched To Markdown

- None

### Check Results

| Check | Status | Message |
|---|---|---|
| chunk_indices_unique | PASS | All 17 chunk_index values are unique |
| chunk_indices_contiguous | PASS | Indices are contiguous from 0..16 |
| chunk_indices_ordered | PASS | Rows are in ascending chunk_index order |
| reconstruction_similarity | PASS | Similarity=1.000000 (markdown=38295 chars, reconstructed=38295 chars) |
| markdown_headers_extracted | PASS | Extracted 20 headers (19 unique paths) |
| toc_required_fields | PASS | All TOC entries contain id/text/level |
| toc_unique_ids | PASS | TOC entry IDs are unique |
| toc_text_values | PASS | All TOC entries have non-empty text |
| toc_level_range | PASS | All TOC levels are in range 1..6 |
| toc_parent_type | PASS | All parent_id values are null or strings |
| toc_parent_references | PASS | All parent references resolve |
| toc_cycles | PASS | No cycles in TOC parent links |
| toc_covers_markdown_headers | PASS | TOC covers all markdown header paths |
| toc_extra_paths | PASS | No extra TOC paths |
| chunk_metadata_schema | PASS | Chunk metadata schema is valid |
| chunk_metadata_empty_paths | PASS | All chunks have non-empty all_header_paths |
| chunk_paths_match_markdown | PASS | All chunk header paths match markdown paths/prefixes |
| chunk_legacy_metadata_keys | PASS | No legacy metadata keys found in chunk metadata |
| document_temp_chunks_cleared | PASS | documents.chunks is NULL for this document |

### Random Chunk Inspection

| Chunk Index | Verdict | Chars | Words | Header Paths | Preview | Notes |
|---:|---|---:|---:|---|---|---|
| 7 | PASS | 2504 | 373 | Fig. 3. | PNAS \| December 13, 2011 \| vol. 108 \| no. 50 \| 20257 Downloaded from https://www.pnas.org by 122.161.48.20 on February 13, 2026 from IP address 122.161.48.20. emerge to “interfere” with a task, control regions may coactivate to monitor and dampen this process. This coactivation of monitoring/control | No metadata issues for this chunk sample |
| 8 | PASS | 769 | 113 | Methods, Subjects | # Methods # Subjects Twelve right-handed individuals with > 10 y and an average of 10,565 ± 5,148 h of mindfulness meditation experience, and 13 healthy volunteers were recruited to participate. Right-handed meditation-naive controls were case-control matched for country of origin (United States), p | No metadata issues for this chunk sample |
| 11 | PASS | 1878 | 263 | Imaging Data Processing, GLM Data Analysis | # Imaging Data Processing Functional images were subjected to standard preprocessing using SPM5 (Wellcome Department of Cognitive Neurology) following our prior published methods (e.g., ref. 38), which included the following steps: slice scan-time correction to the middle slice of each volume; a two | No metadata issues for this chunk sample |

## Document [19] Mindfulness practice leads to increases in regional brain gray matter density

- Status: `completed`
- Final verdict: **WARN**
- Chunk stats: count=41, chars(min/avg/max)=56/2838.3/8555, words(min/avg/max)=9/242.6/662
- Reconstruction: similarity=0.999991 (PASS)
- Headers: markdown_paths=38, toc_paths=38, toc_entries=38
- Check outcomes: PASS=18, WARN=1, FAIL=0

### Missing Markdown Headers In TOC

- None

### Extra TOC Paths Not In Markdown

- None

### Chunk Paths Unmatched To Markdown

- None

### Check Results

| Check | Status | Message |
|---|---|---|
| chunk_indices_unique | PASS | All 41 chunk_index values are unique |
| chunk_indices_contiguous | PASS | Indices are contiguous from 0..40 |
| chunk_indices_ordered | PASS | Rows are in ascending chunk_index order |
| reconstruction_similarity | PASS | Similarity=0.999991 (markdown=116103 chars, reconstructed=116101 chars) |
| markdown_headers_extracted | PASS | Extracted 38 headers (38 unique paths) |
| toc_required_fields | PASS | All TOC entries contain id/text/level |
| toc_unique_ids | PASS | TOC entry IDs are unique |
| toc_text_values | PASS | All TOC entries have non-empty text |
| toc_level_range | PASS | All TOC levels are in range 1..6 |
| toc_parent_type | PASS | All parent_id values are null or strings |
| toc_parent_references | PASS | All parent references resolve |
| toc_cycles | PASS | No cycles in TOC parent links |
| toc_covers_markdown_headers | PASS | TOC covers all markdown header paths |
| toc_extra_paths | PASS | No extra TOC paths |
| chunk_metadata_schema | PASS | Chunk metadata schema is valid |
| chunk_metadata_empty_paths | WARN | 1 chunks have empty all_header_paths |
| chunk_paths_match_markdown | PASS | All chunk header paths match markdown paths/prefixes |
| chunk_legacy_metadata_keys | PASS | No legacy metadata keys found in chunk metadata |
| document_temp_chunks_cleared | PASS | documents.chunks is NULL for this document |

### Random Chunk Inspection

| Chunk Index | Verdict | Chars | Words | Header Paths | Preview | Notes |
|---:|---|---:|---:|---|---|---|
| 16 | PASS | 2766 | 398 | Mindfulness practice leads to increases in regional brain gray matter density > 3. Results > 3.4 Whole brain analysis > Figure 3. | #### Figure 3. ![Figure 3](https://cdn.ncbi.nlm.nih.gov/pmc/blobs/a1b0/3004979/112feb87ac4a/nihms-232587-f0004.jpg) ![Figure 3](https://cdn.ncbi.nlm.nih.gov/pmc/blobs/a1b0/3004979/791f04e79388/nihms-232587-f0005.jpg) ![Figure 3](https://cdn.ncbi.nlm.nih.gov/pmc/blobs/a1b0/3004979/9d99cb83debe/nihms- | No metadata issues for this chunk sample |
| 17 | PASS | 3938 | 545 | Mindfulness practice leads to increases in regional brain gray matter density > 4. Discussion | ## 4. Discussion This study demonstrates longitudinal changes in brain gray matter concentration following an eight-week Mindfulness-Based Stress Reduction course compared to a control group. Hypothesized increases in gray matter concentration within the left hippocampus were confirmed. Exploratory  | No metadata issues for this chunk sample |
| 32 | PASS | 1890 | 75 | Mindfulness practice leads to increases in regional brain gray matter density > References | 2005;102:10706–10711. doi: 10.1073/pnas.0502441102. [[DOI](https://doi.org/10.1073/pnas.0502441102)] [[PMC free article](/articles/PMC1180773/)] [[PubMed](https://pubmed.ncbi.nlm.nih.gov/16024728/)] [[Google Scholar](https://scholar.google.com/scholar_lookup?journal=Proceedings%20of%20the%20National | No metadata issues for this chunk sample |

## Document [27] Research Review: The effects of mindfulness-based interventions on cognition and mental health in children and adolescents - a meta-analysis of randomized controlled trials

- Status: `completed`
- Final verdict: **WARN**
- Chunk stats: count=55, chars(min/avg/max)=56/2413.9/5983, words(min/avg/max)=10/242.6/850
- Reconstruction: similarity=0.999336 (PASS)
- Headers: markdown_paths=56, toc_paths=56, toc_entries=56
- Check outcomes: PASS=18, WARN=1, FAIL=0

### Missing Markdown Headers In TOC

- None

### Extra TOC Paths Not In Markdown

- None

### Chunk Paths Unmatched To Markdown

- None

### Check Results

| Check | Status | Message |
|---|---|---|
| chunk_indices_unique | PASS | All 55 chunk_index values are unique |
| chunk_indices_contiguous | PASS | Indices are contiguous from 0..54 |
| chunk_indices_ordered | PASS | Rows are in ascending chunk_index order |
| reconstruction_similarity | PASS | Similarity=0.999336 (markdown=132553 chars, reconstructed=132377 chars) |
| markdown_headers_extracted | PASS | Extracted 56 headers (56 unique paths) |
| toc_required_fields | PASS | All TOC entries contain id/text/level |
| toc_unique_ids | PASS | TOC entry IDs are unique |
| toc_text_values | PASS | All TOC entries have non-empty text |
| toc_level_range | PASS | All TOC levels are in range 1..6 |
| toc_parent_type | PASS | All parent_id values are null or strings |
| toc_parent_references | PASS | All parent references resolve |
| toc_cycles | PASS | No cycles in TOC parent links |
| toc_covers_markdown_headers | PASS | TOC covers all markdown header paths |
| toc_extra_paths | PASS | No extra TOC paths |
| chunk_metadata_schema | PASS | Chunk metadata schema is valid |
| chunk_metadata_empty_paths | WARN | 1 chunks have empty all_header_paths |
| chunk_paths_match_markdown | PASS | All chunk header paths match markdown paths/prefixes |
| chunk_legacy_metadata_keys | PASS | No legacy metadata keys found in chunk metadata |
| document_temp_chunks_cleared | PASS | documents.chunks is NULL for this document |

### Random Chunk Inspection

| Chunk Index | Verdict | Chars | Words | Header Paths | Preview | Notes |
|---:|---|---:|---:|---|---|---|
| 3 | PASS | 562 | 43 | Research Review: The effects of mindfulness‐based interventions on cognition and mental health in children and adolescents – a meta‐analysis of randomized controlled trials > Kirsty Griffiths, Research Review: The effects of mindfulness‐based interventions on cognition and mental health in children and adolescents – a meta‐analysis of randomized controlled trials > Willem Kuyken | ### Kirsty Griffiths 1Medical Research Council Cognition and Brain Sciences Unit, University of Cambridge, Cambridge, UK Find articles by [Kirsty Griffiths](https://pubmed.ncbi.nlm.nih.gov/?term="Griffiths%20K"[Author]) 1, [Willem Kuyken](https://pubmed.ncbi.nlm.nih.gov/?term="Kuyken%20W"[Author]) # | No metadata issues for this chunk sample |
| 35 | PASS | 4088 | 226 | Research Review: The effects of mindfulness‐based interventions on cognition and mental health in children and adolescents – a meta‐analysis of randomized controlled trials > References | , Grossman, P. , & Walach, H. (2001). Measuring mindfulness in insight meditation (Vipassana) and meditation based psychotherapy: The development of the Freiburg Mindfulness Inventory (FMI). Journal for Meditation and Meditation Research, 1, 11–34. [[Google Scholar](https://scholar.google.com/schola | No metadata issues for this chunk sample |
| 40 | PASS | 1347 | 72 | Research Review: The effects of mindfulness‐based interventions on cognition and mental health in children and adolescents – a meta‐analysis of randomized controlled trials > References | (2015). Does mindfulness meditation increase effectiveness of substance abuse treatment with incarcerated youth? A pilot randomized controlled trial. Mindfulness, 6, 1472–1480. [[Google Scholar](https://scholar.google.com/scholar_lookup?journal=Mindfulness&title=Does%20mindfulness%20meditation%20inc | No metadata issues for this chunk sample |

## Document [28] A mindfulness-based intervention to increase resilience to stress in university students (the Mindful Student Study): a pragmatic randomised controlled trial

- Status: `completed`
- Final verdict: **WARN**
- Chunk stats: count=35, chars(min/avg/max)=56/2266.7/6164, words(min/avg/max)=10/244.9/804
- Reconstruction: similarity=0.999981 (PASS)
- Headers: markdown_paths=50, toc_paths=50, toc_entries=50
- Check outcomes: PASS=18, WARN=1, FAIL=0

### Missing Markdown Headers In TOC

- None

### Extra TOC Paths Not In Markdown

- None

### Chunk Paths Unmatched To Markdown

- None

### Check Results

| Check | Status | Message |
|---|---|---|
| chunk_indices_unique | PASS | All 35 chunk_index values are unique |
| chunk_indices_contiguous | PASS | Indices are contiguous from 0..34 |
| chunk_indices_ordered | PASS | Rows are in ascending chunk_index order |
| reconstruction_similarity | PASS | Similarity=0.999981 (markdown=78938 chars, reconstructed=78935 chars) |
| markdown_headers_extracted | PASS | Extracted 50 headers (50 unique paths) |
| toc_required_fields | PASS | All TOC entries contain id/text/level |
| toc_unique_ids | PASS | TOC entry IDs are unique |
| toc_text_values | PASS | All TOC entries have non-empty text |
| toc_level_range | PASS | All TOC levels are in range 1..6 |
| toc_parent_type | PASS | All parent_id values are null or strings |
| toc_parent_references | PASS | All parent references resolve |
| toc_cycles | PASS | No cycles in TOC parent links |
| toc_covers_markdown_headers | PASS | TOC covers all markdown header paths |
| toc_extra_paths | PASS | No extra TOC paths |
| chunk_metadata_schema | PASS | Chunk metadata schema is valid |
| chunk_metadata_empty_paths | WARN | 1 chunks have empty all_header_paths |
| chunk_paths_match_markdown | PASS | All chunk header paths match markdown paths/prefixes |
| chunk_legacy_metadata_keys | PASS | No legacy metadata keys found in chunk metadata |
| document_temp_chunks_cleared | PASS | documents.chunks is NULL for this document |

### Random Chunk Inspection

| Chunk Index | Verdict | Chars | Words | Header Paths | Preview | Notes |
|---:|---|---:|---:|---|---|---|
| 25 | PASS | 874 | 51 | A mindfulness-based intervention to increase resilience to stress in university students (the Mindful Student Study): a pragmatic randomised controlled trial > Supplementary Material, A mindfulness-based intervention to increase resilience to stress in university students (the Mindful Student Study): a pragmatic randomised controlled trial > References | ## Supplementary Material Supplementary appendix [mmc1.pdf](/articles/instance/5846880/bin/mmc1.pdf) (1MB, pdf) ## References * 1.Patton GC, Sawyer SM, Santelli JS. Our future: a Lancet commission on adolescent health and wellbeing. Lancet. 2016;387:2423–2478. doi: 10.1016/S0140-6736(16)00579-1. [[D | No metadata issues for this chunk sample |
| 29 | PASS | 4244 | 219 | A mindfulness-based intervention to increase resilience to stress in university students (the Mindful Student Study): a pragmatic randomised controlled trial > References | 2009;23:1352–1372. [[Google Scholar](https://scholar.google.com/scholar_lookup?journal=Cogn%20Emot&title=Putting%20appraisal%20in%20context:%20toward%20a%20relational%20model%20of%20appraisal%20and%20emotion&author=CA%20Smith&author=LD%20Kirby&volume=23&publication_year=2009&pages=1352-1372&)] * 23. | No metadata issues for this chunk sample |
| 30 | PASS | 3094 | 152 | A mindfulness-based intervention to increase resilience to stress in university students (the Mindful Student Study): a pragmatic randomised controlled trial > References | 2013;24:776–781. doi: 10.1177/0956797612459659. [[DOI](https://doi.org/10.1177/0956797612459659)] [[PubMed](https://pubmed.ncbi.nlm.nih.gov/23538911/)] [[Google Scholar](https://scholar.google.com/scholar_lookup?journal=Psychol%20Sci&title=Mindfulness%20training%20improves%20working%20memory%20capac | No metadata issues for this chunk sample |

## Document [36] Verses of the Senior Monks (Theragatha)

- Status: `completed`
- Final verdict: **WARN**
- Chunk stats: count=166, chars(min/avg/max)=294/1612.7/17851, words(min/avg/max)=51/285.9/1648
- Reconstruction: similarity=0.999994 (PASS)
- Headers: markdown_paths=341, toc_paths=341, toc_entries=341
- Check outcomes: PASS=18, WARN=1, FAIL=0

### Missing Markdown Headers In TOC

- None

### Extra TOC Paths Not In Markdown

- None

### Chunk Paths Unmatched To Markdown

- None

### Check Results

| Check | Status | Message |
|---|---|---|
| chunk_indices_unique | PASS | All 166 chunk_index values are unique |
| chunk_indices_contiguous | PASS | Indices are contiguous from 0..165 |
| chunk_indices_ordered | PASS | Rows are in ascending chunk_index order |
| reconstruction_similarity | PASS | Similarity=0.999994 (markdown=266902 chars, reconstructed=266899 chars) |
| markdown_headers_extracted | PASS | Extracted 341 headers (341 unique paths) |
| toc_required_fields | PASS | All TOC entries contain id/text/level |
| toc_unique_ids | PASS | TOC entry IDs are unique |
| toc_text_values | PASS | All TOC entries have non-empty text |
| toc_level_range | PASS | All TOC levels are in range 1..6 |
| toc_parent_type | PASS | All parent_id values are null or strings |
| toc_parent_references | PASS | All parent references resolve |
| toc_cycles | PASS | No cycles in TOC parent links |
| toc_covers_markdown_headers | PASS | TOC covers all markdown header paths |
| toc_extra_paths | PASS | No extra TOC paths |
| chunk_metadata_schema | PASS | Chunk metadata schema is valid |
| chunk_metadata_empty_paths | WARN | 2 chunks have empty all_header_paths |
| chunk_paths_match_markdown | PASS | All chunk header paths match markdown paths/prefixes |
| chunk_legacy_metadata_keys | PASS | No legacy metadata keys found in chunk metadata |
| document_temp_chunks_cleared | PASS | documents.chunks is NULL for this document |

### Random Chunk Inspection

| Chunk Index | Verdict | Chars | Words | Header Paths | Preview | Notes |
|---:|---|---:|---:|---|---|---|
| 36 | PASS | 343 | 59 | The Book of the Ones > Chapter Five > Thag 1.48Sañjaya Sañjayattheragāthā, The Book of the Ones > Chapter Five > Thag 1.49Rāmaṇeyyaka Rāmaṇeyyakattheragāthā | ### Thag 1.48Sañjaya Sañjayattheragāthā > Since I went forth > from the lay life to homelessness, > I’ve not been aware of any thought > that is ignoble and hateful. ### Thag 1.49Rāmaṇeyyaka Rāmaṇeyyakattheragāthā > Even with all the sounds, > the chirping and cheeping of the birds, > my mind doesn’ | No metadata issues for this chunk sample |
| 77 | PASS | 1460 | 257 | The Book of the Twos > Chapter Two > Thag 2.16Mahākāḷa Mahākāḷattheragāthā, The Book of the Twos > Chapter Two > Thag 2.17Tissa (3rd) Tissattheragāthā, The Book of the Twos > Chapter Two > Thag 2.18Kimbila (2nd) Kimilattheragāthā, The Book of the Twos > Chapter Two > Thag 2.19Nanda Nandattheragāthā | ### Thag 2.16Mahākāḷa Mahākāḷattheragāthā > There’s a big black woman who looks like a crow. > She broke off thigh-bones, first one then another; > she broke off arm-bones, first one then another; > she broke off a skull like a curd-bowl, and then > arranged them and sat nearby. > > When an ignorant | No metadata issues for this chunk sample |
| 109 | PASS | 1660 | 303 | The Book of the Sixes > Chapter One > Thag 6.10Sumana (2nd) Sumanattheragāthā, The Book of the Sixes > Chapter One > Thag 6.11Nhātakamuni Nhātakamunittheragāthā | ### Thag 6.10Sumana (2nd) Sumanattheragāthā > I was only seven years old > and had just gone forth > when I overcame the mighty adder king > with my psychic powers. > > I brought water for my mentor > from the great lake Anotatta. > When he saw me, > my teacher declared: > > “Sāriputta, see this > y | No metadata issues for this chunk sample |

## Appendix

- Seed: `42`
- Sampled document IDs: `17, 19, 27, 28, 36`

### Validation Rules

- Reconstruction similarity: PASS `>= 0.995`, WARN `0.98-0.995`, FAIL `< 0.98`.
- Unmatched chunk paths: FAIL if count `>= 3`; otherwise WARN.
- TOC missing markdown paths: FAIL.
- Extra TOC paths not in markdown: WARN.
