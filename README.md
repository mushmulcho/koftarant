# Тарантският кофаджия — архив и търсачка

The sessions are written on Blogger as usual. This site copies the blog every night
(posts, comments and images) into this repository and publishes a searchable version.

- **Blog address:** set in `config.json`.
- **Nightly copy:** `.github/workflows/update.yml` runs `scripts/update.py` at about 04:17 Sofia time.
  To run it right away: **Actions → Copy blog and publish site → Run workflow**.
- **Backup:** `data/posts.json` holds every post and comment; `images/` holds every image.
  Posts deleted from the blog stay here, marked as removed.
- **Look of the site:** everything is in `index.html` (colours at the top, in `:root`).
