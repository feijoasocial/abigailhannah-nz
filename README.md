# abigailhannah.nz

Static site for Abigail Hannah: the home of the Aotearoa Adventures podcast, the blog, and the NZ Road Trip Adventure Guide (sold on Rexby).

## How it works

- `build.py` renders `templates/` with Jinja2 into `dist/`.
- `content/episodes/*.md` are the long-form episode posts (recovered from the old WordPress site). `content/posts/*.md` are articles. YAML front matter + Markdown.
- The Captivate podcast feed is fetched at build time and merged with the episode posts by episode number. Every episode in the feed gets a page, with or without a post. `data/feed.xml` is the last good snapshot and the fallback if the feed is unreachable.
- Every old WordPress URL is reproduced at the same path, so no redirects are needed.
- `config.yml` holds every outbound link and embed. Change a link there, never in a template.
- GitHub Actions rebuilds on every push, every Friday after the episode drops, and daily as a catch-up. Deploys to GitHub Pages.

## Adding full show notes to an episode

Create `content/episodes/<slug>.md` with front matter (`title`, `slug`, `date`, `episode`, `spotify`, `image`, `description`) and the notes as Markdown. The page at `/<slug>/` then uses the notes instead of the feed description.

## Local build

    pip install -r requirements.txt
    python3 build.py            # live feed
    python3 build.py --offline  # snapshot only
