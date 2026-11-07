#!/bin/sh
# Compile les deux manuels (deux passes pour la table des matières), les
# place dans docs/, puis supprime les fichiers temporaires de LaTeX.
set -e
cd "$(dirname "$0")"
printf '\\newcommand{\\versioncalque}{%s}\n' "$(tr -d ' \r\n' < ../../VERSION)" > version.tex
for lg in fr en; do
  for passe in 1 2; do
    pdflatex -interaction=nonstopmode -halt-on-error "manuel-$lg.tex" > /dev/null \
      || { grep -A6 '^!' "manuel-$lg.log" | head -20; exit 1; }
  done
  grep -c 'Overfull' "manuel-$lg.log" | sed "s/^/manuel-$lg : débordements = /"
  mv -f "manuel-$lg.pdf" ..
done
rm -f *.aux *.log *.out *.toc version.tex
