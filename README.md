# StillInLife

Ogni giorno alle **09:00 (ora italiana)** un agente legge le notizie del giorno,
ne distilla **un oggetto fisico** e lo dipinge dentro una natura morta barocca
(*pronkstilleven*) al buio quasi totale. Ogni immagine è una **fetta** di una
tavola infinita: le fette si affiancano e si possono scorrere in orizzontale.

## Come funziona

```
cron 09:00 IT → Google News RSS → Claude estrae 1 oggetto
             → prompt pronkstilleven + oggetto del giorno
             → Nano Banana 2 (Kie.ai) dipinge la fetta, in continuità con ieri
             → commit di output/AAAA-MM-GG.png + state/manifest.json
```

- `scripts/generate.py` — tutta la logica.
- `prompt_config.json` — lo stile fisso (tavolo, buio, pool di oggetti).
- `reference/Table1.png` — il tavolo di riferimento, àncora fissa di tutte le fette.
- `state/manifest.json` — archivio: data, oggetto, notizia, simbolismo per ogni fetta.
- `index.html` — viewer a nastro orizzontale (GitHub Pages).
- `.github/workflows/daily.yml` — il cron.

## Setup (una volta)

1. Crea il repo **pubblico** e carica questi file.
2. **Settings → Secrets and variables → Actions → New repository secret**:
   - `ANTHROPIC_API_KEY`
   - `KIE_API_KEY`
3. **Settings → Pages → Source: Deploy from a branch → `main` / root** (per il viewer).
4. **Actions → StillInLife daily slice → Run workflow** per generare subito la prima fetta di prova.

Poi va da solo, una fetta al giorno.

## Costi

- GitHub Actions: gratis (repo pubblico).
- Google News RSS: gratis.
- Kie.ai (Nano Banana 2): ~$0.04–0.05/immagine → **~1–1,5 $/mese**.
- Claude API: pochi centesimi al mese.

## Note

- Il cron GitHub è UTC e non gestisce l'ora legale: due orari (07/08 UTC) + una
  guardia su `Europe/Rome == 09:00` fanno partire il run una volta sola al giorno.
- La continuità tra fette è "best effort": stessa altezza/tavolo/buio + il bordo
  destro di ieri come reference. Non è perfetta al pixel — i modelli text-to-image
  non garantiscono geometria esatta.
