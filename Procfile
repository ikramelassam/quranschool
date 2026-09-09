# --timeout 60 (au lieu de 30) : chien de garde « worker figé », PAS un quota de
#   durée — ne ralentit aucune requête rapide. À 30 s, une page lourde sur base
#   Supabase froide (cold start / handshake pooler) était tuée avant d'aboutir
#   -> page blanche pour l'utilisateur (diag AUDIT_STABILITE_2026-09-09.md §1.2).
# --max-requests 500 --max-requests-jitter 100 : chaque worker se recycle
#   proprement (un à la fois, décalé par le jitter) après ~500 requêtes ->
#   la mémoire Python accumulée est relâchée régulièrement au lieu d'attendre
#   un OOM-kill de Render (512 Mo, plan free) qui, lui, coupe net les requêtes
#   en cours (§1.1 du même audit — problème mémoire confirmé côté Render).
# --preload : l'app Django est chargée UNE fois dans le master puis forkée ->
#   les pages mémoire immuables sont partagées entre les 2 workers (copy-on-
#   write) au lieu d'être dupliquées. Gain net sur un service à 512 Mo. Sans
#   effet de bord ici : aucune connexion DB / handle fichier ouvert à l'import
#   (CONN_MAX_AGE crée les connexions après le fork, à la 1re requête de chaque
#   worker). Render redémarre de toute façon tout le service à chaque déploiement.
# --graceful-timeout 30 : délai laissé à un worker pour finir ses requêtes en
#   cours quand il est recyclé (max-requests) ou redémarré, avant kill.
web: gunicorn core.wsgi --workers 2 --worker-class gthread --threads 4 --timeout 60 --graceful-timeout 30 --max-requests 500 --max-requests-jitter 100 --preload --worker-tmp-dir /dev/shm --log-file -
