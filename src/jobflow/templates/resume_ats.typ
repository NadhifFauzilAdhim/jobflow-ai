#set page(paper: "us-letter", margin: (x: 1.5cm, y: 1.5cm))
#set text(font: "Linux Libertine", size: 10pt)
#set par(justify: true, leading: 0.55em)

// Header
#align(center)[
  #text(size: 16pt, weight: "bold")[NAME_PLACEHOLDER] \
  #v(-2pt)
  #text(size: 8.5pt)[CONTACT_PLACEHOLDER]
]

#v(4pt)
#line(length: 100%, stroke: 0.5pt + luma(120))

// Section function
#let section(title) = [
  #v(6pt)
  #text(size: 10.5pt, weight: "bold", fill: rgb("#111827"))[#upper(title)]
  #v(-4pt)
  #line(length: 100%, stroke: 0.4pt + luma(180))
  #v(2pt)
]

SUMMARY_SECTION_PLACEHOLDER

SKILLS_SECTION_PLACEHOLDER

EXPERIENCE_SECTION_PLACEHOLDER

PROJECTS_SECTION_PLACEHOLDER

EDUCATION_SECTION_PLACEHOLDER
