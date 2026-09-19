# Lyricsfinder

Lyricsfinder est une application desktop en Python (CustomTkinter) qui affiche les paroles de la musique en cours, avec traduction ligne par ligne et synchronisation quand des paroles horodatées sont disponibles.

## Fonctionnalités

- Détection automatique du titre/artiste en lecture (Windows media session)
- Recherche des paroles via **lrclib** (priorité), puis fallback **Genius**
- Affichage des paroles synchronisées (mode karaoké) si disponible
- Traduction automatique des lignes (Bing via `translators`)
- Changement de langue de traduction (`fr`, `en`, `es`, `de`, `it`, `pt`)
- Recherche manuelle (`Artiste - Titre`)
- Mode mini et ajustement d’offset de synchro
- Cache local des traductions dans `lyrics_cache.json`

## Prérequis

- **Windows** (la récupération du média en cours utilise `winrt`)
- Python 3.10+

## Installation

1. Cloner le dépôt.
2. Installer les dépendances :

```bash
pip install customtkinter requests beautifulsoup4 translators winrt-runtime winrt-Windows.Media.Control
```

## Lancer l’application

Depuis la racine du projet :

```bash
python main.py
```

## Utilisation rapide

- Lance une musique sur ton lecteur (Spotify, navigateur, etc.).
- L’application récupère automatiquement le titre et l’artiste.
- Active/désactive :
  - **Trad** pour afficher la traduction
  - **Sync** pour le suivi karaoké (quand disponible)
- Clique sur **🔍** pour faire une recherche manuelle.
- Utilise **Mode Mini** pour un affichage compact.

## Notes

- Si aucune source ne trouve les paroles, l’interface indique que les paroles sont introuvables.
- Le cache (`lyrics_cache.json`) accélère les traductions déjà faites.
