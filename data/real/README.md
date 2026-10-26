# Real addresses - collection protocol

Purpose: an honest test set of real Bangladeshi addresses, to measure how a
model trained on synthetic data performs on reality. NEVER used for training.

Rules:
1. Only addresses I have permission to use: my own, family with their
   agreement, or ones a seller shares for this project.
2. Remove recipient names and phone numbers before saving (replace with
   <NAME> / <PHONE>). Keep the address itself exactly as written.
3. Record it EXACTLY as written, including typos, odd spacing and mixed
   scripts. Cleaning it up defeats the purpose.
4. Target 150-300 addresses: mixed English / Banglish / Bangla script,
   mixed urban and rural.

File: addresses_raw.csv   columns: id,source,collected_on,script,raw_address
This CSV is gitignored on purpose: it is personal data.

STATUS (2026-10-26): EMPTY. No real addresses have been collected yet.
A hand-written stand-in set exists in data/handwritten/ and is NOT real data.
Never move invented addresses into this folder: everything downstream treats
"real" as "collected from real people".
