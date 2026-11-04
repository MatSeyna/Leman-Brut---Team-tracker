# Leman Brut – team tracker (Warhammer 40K)

Small web app (installable on Android) with:
- faction **win rates** for the last week / month / 3 months
- **matchups** faction vs faction
- **dispositions** (real results + author ratings + your own ratings)
- army **lists** and a 5×5 **priority grid** (kept on each device)

## How the data works
`scripts/scrape.py` runs every day through GitHub Actions (`.github/workflows/daily.yml`).
It reads the public stats pages of MiniHeadQuarters for three time windows
(last week, last 4 weeks, last 12 weeks) and saves, under `data/`:

| file | content |
|---|---|
| `latest.json` | newest full snapshot, read by the app |
| `trend.json` | win rate per faction and window, one point per day |
| `history/DATE.json.gz` | full snapshot of each day |
| `update_log.json` | one line per run: did the numbers change since the day before? |

If the site is down or its layout changes, the run fails and the previous data stays in place.

The windows are the ones the site itself computes (rolling), so they are not rebuilt from our own days.
The daily history is what gives the trend.

## Setup (once)
1. **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, folder `/ (root)`.
2. **Actions** tab → *Daily stats snapshot* → *Run workflow* to fetch the first data without waiting for tomorrow.
3. Open the Pages address on the phone in Chrome → menu → *Add to Home screen*.

## Please be polite to the data source
One run per day, about 130 requests, with a pause between them and robots.txt respected.
Check MiniHeadQuarters' terms of use before relying on this, or ask them for permission.

## Comptes, équipes et partage (Supabase)

1. Créer un projet gratuit sur supabase.com, exécuter `supabase/schema.sql` dans *SQL Editor*.
2. *Authentication → URL Configuration* : « Site URL » = l'adresse de l'app. Garder « Confirm email » activé.
3. Mettre l'URL du projet et la clé *anon public* dans `config.js` (ou les coller dans l'onglet Équipe).
4. Le compte `matthieu.seynaeve.pro@hotmail.com` devient automatiquement l'administrateur **Iscalis** (après confirmation de l'e-mail). Les autres comptes doivent être validés par lui, puis chaque joueur demande à rejoindre une équipe, validé par un responsable ou capitaine.
