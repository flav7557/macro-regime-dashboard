# Macro Regime Dashboard

Un tableau de bord **automatique, gratuit et 100 % interprétable** qui détermine chaque jour le **régime de marché** à partir des clôtures de la veille (actions, taux, FX, crédit, matières premières, volatilité).

Pas de machine learning, pas de boîte noire : chaque régime est défini par des **règles lisibles** (confirmations + contradictions, avec poids) dans un fichier YAML. Le résultat est une page HTML statique, publiable gratuitement sur **GitHub Pages** et mise à jour quotidiennement via **GitHub Actions**.

---

## 1. Objectif

Répondre à une question simple chaque matin : **dans quel régime le marché se trouve-t-il ?**

Le moteur évalue 16 régimes (Risk-On, Risk-Off, Recession Scare, Inflation Shock, Rates Shock, Goldilocks, Commodity Reflation, Stagflation, Dollar Squeeze, Credit Stress, Defensive Rotation, Tech-Led Risk-On, Safe-Haven Bid, Energy Supply Shock, EM Stress, Neutral/Mixed) et attribue à chacun un **score de correspondance** entre 0 et 100 %. Le régime dominant est mis en avant, et chaque carte est dépliable pour voir **exactement quelles règles ont été déclenchées** et avec quelles données.

> ⚠️ **Outil éducatif, pas un conseil en investissement.** Les scores sont des mesures déterministes de correspondance, **pas des probabilités** ni des prévisions.

---

## 2. Installation

Prérequis : Python 3.10+.

```bash
git clone <votre-repo>.git
cd macro-regime-dashboard
pip install -r requirements.txt
```

---

## 3. Utilisation

**Données réelles (Yahoo Finance, gratuit) :**

```bash
python run.py
```

**Mode hors-ligne / démo (données synthétiques, aucune connexion requise) :**

```bash
python run.py --source synthetic
```

**Période d'historique personnalisée :**

```bash
python run.py --period 5y
```

Puis ouvrez le fichier généré dans un navigateur :

```
output/index.html
```

Le script écrit aussi :

- `output/macro_regime_dashboard.html` — copie identique (nom explicite) ;
- `data/regime_history.csv` — une ligne ajoutée à chaque exécution (historique des régimes) ;
- `data/processed/last_run.json` — résumé de la dernière exécution ;
- `data/raw/close_prices.csv` — fin de série des prix de clôture.

---

## 4. Comment lire le tableau de bord

### Score de correspondance (0–100 %)

Pour chaque régime :

```
raw   = poids_confirmations_obtenues / poids_confirmations_possibles × 100
score = raw × (1 − pénalité_contradiction × ratio_contradictions)
            × (1 − pénalité_donnée_manquante × ratio_manquant)
```

- Une **donnée manquante** (ticker indisponible) ne compte pas au dénominateur mais réduit légèrement la confiance.
- Le **%** est un score de **correspondance / confiance**, pas une probabilité statistique.

Les pénalités sont réglables dans `config/regimes.yml` (`settings`) :

| Paramètre | Défaut | Effet |
|---|---|---|
| `contradiction_penalty` | 0.35 | des contradictions actives réduisent le score (jusqu'à −35 %) |
| `missing_penalty` | 0.15 | beaucoup de données manquantes réduisent la confiance (jusqu'à −15 %) |
| `neutral_threshold` | 55 | si le meilleur régime est en dessous → **Neutral/Mixed** |
| `mixed_ceiling` / `mixed_gap` | 60 / 5 | meilleur régime sous 60 **et** 2ᵉ à moins de 5 pts → Neutral/Mixed (avec biais) |

### Scores macro agrégés (−100 … +100)

Dix scores synthétiques (Equity Risk, Credit Risk, Rates Pressure, Dollar Stress, Commodity Inflation, Volatility Stress, etc.) construits comme la moyenne de **z-scores 1 jour signés**, mis à l'échelle (×30) et bornés à ±100. Ils servent à la fois d'indicateurs lisibles et d'entrées aux règles (ex. `score.rates_pressure > 40`).

### Règles

Chaque règle compare une **feature** à un seuil (ou à une autre feature) :

```yaml
- {n: "10Y yield rising", f: US10Y.change_1d_bps, op: ">", t: 5.0, w: 2, k: c, why: "the 10Y yield is rising"}
```

- `f` = feature (ex. `SPY.return_1d`, `HYG/LQD.return_1d`, `US10Y.change_1d_bps`, `score.equity_risk`)
- `op` = `<`, `>`, `<=`, `>=` · `t` = seuil · `cf` = comparer à une autre feature (ex. `IWM` vs `SPY`)
- `w` = poids · `k` = `c` (confirmation) ou `x` (contradiction) · `why` = phrase d'explication

Les features disponibles par actif : `return_1d/5d/20d`, `zscore_1d/5d`, `zlevel`, `realized_vol_20d`, `dist_high_20d`, `dist_low_20d`, `last` ; pour les taux : `level`, `change_1d_bps/5d_bps/20d_bps`, `zscore_1d`.

---

## 5. Personnalisation

### Ajouter un actif

Dans `config/assets.yml`, ajoutez une ligne sous `assets:` :

```yaml
  XLB: {ticker: "XLB", label: "Materials", category: "Sector"}
```

Pour l'afficher dans le tableau « Market moves », ajoutez son alias à `market_table:`. Pour créer un ratio de force relative, ajoutez-le à `ratios:` (ex. `"XLB/SPY"`).

### Modifier ou créer un régime

Tout est dans `config/regimes.yml`. Copiez un bloc `- key: ...`, changez le `name`, la `tone` (couleur), la `definition` et la liste de `rules`. Le moteur est générique : aucune ligne de Python à toucher. Couleurs disponibles : `green, emerald, teal, blue, indigo, purple, amber, orange, brown, crimson, rose, red, slate, gray`.

### Régler la sensibilité

Ajustez les seuils `t` des règles ou les `settings` globaux. Des seuils plus stricts → moins de faux positifs mais plus de jours « Neutral/Mixed ».

---

## 6. Déploiement sur GitHub Pages (gratuit, automatique)

1. **Créez un dépôt GitHub** et poussez ce projet :
   ```bash
   git init
   git add .
   git commit -m "Initial commit: macro regime dashboard"
   git branch -M main
   git remote add origin https://github.com/<vous>/<repo>.git
   git push -u origin main
   ```
2. Dans le dépôt : **Settings → Pages → Build and deployment → Source : GitHub Actions**.
3. Onglet **Actions** : ouvrez le workflow *Update Macro Regime Dashboard* et lancez-le une première fois avec **Run workflow** (`workflow_dispatch`).
4. À la fin du job, l'URL de la page apparaît dans l'étape *Deploy to GitHub Pages* (et dans Settings → Pages). Format habituel : `https://<vous>.github.io/<repo>/`.
5. Ensuite, le workflow tourne **automatiquement chaque jour** (cron `30 6 * * 1-5`, soit 06:30 UTC du lundi au vendredi). Il régénère la page, ré-archive `regime_history.csv` et redéploie.

Le commit d'historique utilise `[skip ci]` et le workflow ne se déclenche pas sur `push` : **pas de boucle d'exécution**.

> Pour changer l'heure, modifiez la ligne `cron` dans `.github/workflows/update-dashboard.yml` (syntaxe cron en **UTC**).

---

## 7. Architecture

```
macro-regime-dashboard/
├── config/
│   ├── assets.yml        # univers d'actifs, ratios, ordre des tableaux
│   └── regimes.yml       # 16 régimes + règles + réglages de scoring
├── src/
│   ├── data_loader.py    # yfinance (+ fallback) / générateur synthétique
│   ├── features.py       # returns, z-scores, nettoyage des taux, scores agrégés
│   ├── regime_engine.py  # évaluation des règles, scoring, sélection du régime
│   ├── html_report.py    # rendu des fragments HTML
│   └── utils.py          # formatage, libellés, comparaisons
├── templates/
│   └── dashboard_template.html   # coquille HTML + CSS + JS (autonome)
├── output/
│   └── index.html        # page générée (entrée GitHub Pages)
├── data/
│   └── regime_history.csv
├── run.py                # orchestration
├── requirements.txt
└── .github/workflows/update-dashboard.yml
```

---

## 8. Limites méthodologiques

- Le tableau de bord lit les **clôtures de la veille** : c'est un état des lieux, pas un signal intrajournalier ni une prévision.
- Les régimes sont des **heuristiques** : ils résument des configurations connues, mais le marché peut être ambigu (d'où *Neutral/Mixed*).
- Les seuils sont **fixes et choisis à dire d'expert** ; ils ne sont pas calibrés statistiquement.
- Les données publiques (Yahoo Finance) peuvent comporter des trous, des décalages ou des erreurs ponctuelles.
- Le score n'est **pas une probabilité** et ne doit pas être interprété comme tel.

---

## 9. Avertissement

Ce projet est fourni **à des fins éducatives et d'information uniquement**. Il ne constitue **pas un conseil en investissement**, ni une recommandation d'achat ou de vente d'un quelconque instrument financier. Vous êtes seul responsable de vos décisions. Aucune garantie n'est donnée quant à l'exactitude des données ou des analyses.
