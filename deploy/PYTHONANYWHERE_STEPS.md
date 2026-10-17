# Putting the site on PythonAnywhere (free account)

Files in this folder:

| File | What it is | Size |
|---|---|---|
| `site.zip` | the whole site: code, styling, covers, photos and the database (the same data your friends already use on the test link, with their accounts) | ~5 MB |
| `songs_1.zip`, `songs_2.zip` | the full-length MP3s (optional, step 6) | ~70 MB each |

Your site address will be **https://YOUR-USERNAME.pythonanywhere.com** (your username in lower case).
Below, `YOUR-USERNAME` means the username you signed up with.

---

## 1. Upload the site
1. On PythonAnywhere open the **Files** tab. You are in your home folder (`/home/YOUR-USERNAME`).
2. Click **Upload a file** and choose `site.zip`.

## 2. Unpack it and install Django (Bash console)
Open **Consoles → Bash** and paste these one at a time (wait for each to finish):

```bash
mkdir -p ~/spotify_clone && cd ~/spotify_clone
unzip -o ~/site.zip
ls /usr/bin/python3.*
```
The last command lists the Python versions PythonAnywhere has. Django 6 needs **3.12 or newer**.
Use the newest one in the list in place of `python3.13` below (and remember it for step 3):

```bash
mkvirtualenv spotifyenv --python=python3.13
pip install -r requirements.txt
python -c "import secrets; print(secrets.token_urlsafe(50))" > secret_key.txt
export DJANGO_SETTINGS_MODULE=mysite.settings_prod
python manage.py collectstatic --noinput
python manage.py migrate
pwd
```
`pwd` prints the full path of the project (like `/home/YOUR-USERNAME/spotify_clone`). Keep it handy.

## 3. Create the web app
1. Open the **Web** tab → **Add a new web app** → Next.
2. Choose **Manual configuration** (not "Django") → pick the **same Python version** you used for `mkvirtualenv` → Next.
3. On the web app page set:
   - **Source code:** `/home/YOUR-USERNAME/spotify_clone`
   - **Virtualenv:** `/home/YOUR-USERNAME/.virtualenvs/spotifyenv`
   - **Force HTTPS:** switch it on (Security section).

## 4. The WSGI file
On the Web tab click the link next to **WSGI configuration file** (`/var/www/..._wsgi.py`).
Delete everything in it and paste exactly this, then **Save**:

```python
import os
import sys

path = os.path.expanduser('~/spotify_clone')
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'mysite.settings_prod'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

## 5. Static files (important, otherwise the page has no styling)
On the Web tab, in the **Static files** section add these three rows (URL on the left, folder on the right):

| URL | Directory |
|---|---|
| `/static/` | `/home/YOUR-USERNAME/spotify_clone/staticfiles` |
| `/media/covers/` | `/home/YOUR-USERNAME/spotify_clone/media/covers` |
| `/media/artists/` | `/home/YOUR-USERNAME/spotify_clone/media/artists` |

**Do not** add a row for `/media/audio/`. The songs must go through the site so that only signed-in people can play them.

Press the green **Reload** button at the top of the Web tab, then open your address. You should see the login page.

## 6. The full songs (optional)
Skip this if you only want the 30-second previews. Without it, the tracks that use your own MP3s
(Arthur Nery and a few others) show "couldn't play this track".

The free account has 512 MB, so do the two zips **one after the other**:

1. Files tab → upload `songs_1.zip`. In the Bash console:
   ```bash
   cd ~/spotify_clone && unzip -o ~/songs_1.zip && rm ~/songs_1.zip
   ```
2. Upload `songs_2.zip`, then:
   ```bash
   cd ~/spotify_clone && unzip -o ~/songs_2.zip && rm ~/songs_2.zip
   ```
3. Web tab → **Reload**.

These are copyrighted recordings. Only people with an account on your site can play them, but keep
the link to people you trust, and remove them (`rm -r ~/spotify_clone/media/audio`) if you stop needing them.

---

## Later: updating the site
Upload a new `site.zip` (I can rebuild it), then in the Bash console:

```bash
cd ~/spotify_clone
unzip -o ~/site.zip -x db.sqlite3 'media/*'
export DJANGO_SETTINGS_MODULE=mysite.settings_prod
workon spotifyenv
python manage.py collectstatic --noinput
python manage.py migrate
```
Then press **Reload** on the Web tab. The `-x db.sqlite3` part keeps the accounts and data your friends created.

## Good to know about the free account
- A free web app is switched off after 3 months unless you press **Run until 3 months from today** on the Web tab (they email you first).
- You get about 100 seconds of CPU a day. Browsing is tiny, but lots of full-song streaming from many people at once could use it up; the site then pauses until the next day.
- The site needs no internet access from the server (the 30-second previews are fetched by your friends' browsers), so the free account's limited outgoing access does not matter.
- If something shows an error page, the **Web tab → Error log** link shows why. Send me that text and I'll fix it.
