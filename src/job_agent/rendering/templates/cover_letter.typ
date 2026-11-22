// Custom offline Cover Letter template matching cv.typ header, typography, accent, and margins.
#let data = json(bytes(sys.inputs.data))
#let raw_body_size = float(sys.inputs.at("body_font_size_pt", default: "10.0"))
#assert(
  raw_body_size >= 9.0 and raw_body_size <= 12.0,
  message: "body_font_size_pt must be strictly within [9.0, 12.0]",
)
#let body_size = raw_body_size * 1pt

#let accent = rgb("#26428b")
#let heading_ink = rgb("#111827")
#let ink = rgb("#1f2937")
#let muted = rgb("#4b5563")

#set page(
  paper: "a4",
  margin: (top: 1.25cm, bottom: 1.25cm, left: 1.4cm, right: 1.4cm),
)
#set text(
  font: "Libertinus Serif",
  size: body_size,
  fill: ink,
  lang: data.language,
)
#set par(leading: 0.62em, spacing: 0.9em, justify: false)

#let has-text(val) = val != none and val.trim() != ""

#let format-link(url) = {
  let href = if url.starts-with("http://") or url.starts-with("https://") {
    url
  } else {
    "https://" + url
  }
  link(href)[#url]
}

#let render-header(d) = {
  text(size: 18pt, weight: "bold", fill: heading_ink)[#d.full_name]
  v(0.2em)

  let contacts = ()
  contacts.push(link("mailto:" + d.email)[#d.email])
  if has-text(d.at("phone", default: none)) {
    contacts.push([#d.phone])
  }
  if has-text(d.at("location", default: none)) {
    contacts.push([#d.location])
  }
  if has-text(d.at("linkedin_url", default: none)) {
    contacts.push(format-link(d.linkedin_url))
  }
  if has-text(d.at("github_url", default: none)) {
    contacts.push(format-link(d.github_url))
  }
  if has-text(d.at("website_url", default: none)) {
    contacts.push(format-link(d.website_url))
  }

  text(size: 9pt, fill: muted)[#contacts.join([  |  ])]
  v(0.25em)
  line(length: 100%, stroke: 0.8pt + accent)
}

#render-header(data)

#v(1.1em)
#grid(
  columns: (1fr, auto),
  gutter: 0.6em,
  [
    #strong(data.recipient_company) \
    #text(fill: accent, weight: "bold")[#data.role_title]
  ],
  align(right)[#text(fill: muted)[#data.date_str]],
)

#v(1.0em)
#data.greeting

#v(0.35em)
#for paragraph in data.paragraphs [
  #paragraph
  #parbreak()
]

#v(0.6em)
#data.sign_off \
#v(0.4em)
#strong(data.full_name)
