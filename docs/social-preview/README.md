# Картинка для ссылок на репозиторий

`jericho-social.png` (1280×640) — карточка, которую показывают мессенджеры и соцсети по ссылке на репозиторий
(Social preview в настройках GitHub). `jericho-social.svg` — её исходник для правок.

Пересборка PNG (ImageMagick; для текста нужен шрифт Google Sans Flex):

```bash
magick -background '#f4f2e9' docs/social-preview/jericho-social.svg -alpha remove -alpha off -depth 8 -strip PNG24:docs/social-preview/jericho-social.png
```

Стрелки в SVG нарисованы залитыми прямоугольниками и треугольниками, а не линиями с маркерами: ImageMagick при
сборке терял линии и маркеры. После любой правки SVG — пересобрать PNG и осмотреть его.
