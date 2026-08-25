rmdir /s /q .git
git init
git add -A
git commit -m "clean deployment"
git branch -M main
git remote add origin https://github.com/metallicatw/market-monitor.git
git push -f origin main