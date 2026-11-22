// Offline single-column ATS-friendly CV template (basic-resume inspired).
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

#let labels_by_lang = (
  en: (
    profile: "Profile",
    experience: "Experience",
    projects: "Projects",
    education: "Education",
    skills: "Skills",
    certifications: "Certifications",
    languages: "Languages",
    present: "Present",
  ),
  da: (
    profile: "Profil",
    experience: "Erfaring",
    projects: "Projekter",
    education: "Uddannelse",
    skills: "Kompetencer",
    certifications: "Certificeringer",
    languages: "Sprog",
    present: "Nu",
  ),
)
#let labels = labels_by_lang.at(data.language, default: labels_by_lang.en)

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
#set par(leading: 0.52em, spacing: 0.55em, justify: false)
#set list(indent: 0.6em, body-indent: 0.45em, spacing: 0.3em)

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

#let section-heading(title) = {
  v(0.6em)
  block(breakable: false, spacing: 0pt)[
    #text(size: body_size + 1.5pt, weight: "bold", fill: accent)[#title]
    #v(-0.55em)
    #line(length: 100%, stroke: 0.55pt + accent)
  ]
  v(0.3em)
}

#let render-bullet(b) = {
  if has-text(b.at("lead", default: none)) {
    list.item([#strong(b.lead + ":") #b.text])
  } else {
    list.item([#b.text])
  }
}

#let render-experience(experiences) = {
  if experiences.len() == 0 { return }
  section-heading(labels.experience)
  for (idx, exp) in experiences.enumerate() {
    let end_str = if has-text(exp.at("end_date", default: none)) {
      exp.end_date
    } else {
      labels.present
    }
    let date_range = exp.start_date + " – " + end_str

    block(breakable: false)[
      #grid(
        columns: (1fr, auto),
        gutter: 0.6em,
        [#strong(exp.title)],
        align(right)[#text(fill: muted)[#date_range]],
      )
      #v(-0.3em)
      #grid(
        columns: (1fr, auto),
        gutter: 0.6em,
        [#emph(exp.company)],
        if has-text(exp.at("location", default: none)) {
          align(right)[#text(fill: muted)[#exp.location]]
        } else {
          []
        },
      )
    ]
    if exp.bullets.len() > 0 {
      v(0.15em)
      for b in exp.bullets {
        render-bullet(b)
      }
    }
    if idx < experiences.len() - 1 {
      v(0.35em)
    }
  }
}

#let render-projects(projects) = {
  if projects.len() == 0 { return }
  section-heading(labels.projects)
  for (idx, proj) in projects.enumerate() {
    block(breakable: false)[
      #grid(
        columns: (1fr, auto),
        gutter: 0.6em,
        [#strong(proj.name)],
        if has-text(proj.at("url", default: none)) {
          align(right)[#text(size: 9pt, fill: muted)[#format-link(proj.url)]]
        } else {
          []
        },
      )
    ]
    if proj.bullets.len() > 0 {
      v(0.15em)
      for b in proj.bullets {
        render-bullet(b)
      }
    }
    if idx < projects.len() - 1 {
      v(0.35em)
    }
  }
}

#let render-education(education) = {
  if education.len() == 0 { return }
  section-heading(labels.education)
  for (idx, edu) in education.enumerate() {
    let has_start = has-text(edu.at("start_date", default: none))
    let has_end = has-text(edu.at("end_date", default: none))
    let date_range = if has_start and has_end {
      edu.start_date + " – " + edu.end_date
    } else if has_end {
      edu.end_date
    } else if has_start {
      edu.start_date + " – " + labels.present
    } else {
      ""
    }

    block(breakable: false)[
      #grid(
        columns: (1fr, auto),
        gutter: 0.6em,
        [#strong(edu.degree)],
        if date_range != "" {
          align(right)[#text(fill: muted)[#date_range]]
        } else {
          []
        },
      )
      #v(-0.3em)
      #grid(
        columns: (1fr, auto),
        gutter: 0.6em,
        [#emph(edu.institution)],
        if has-text(edu.at("location", default: none)) {
          align(right)[#text(fill: muted)[#edu.location]]
        } else {
          []
        },
      )
    ]
    if edu.highlights.len() > 0 {
      v(0.15em)
      for h in edu.highlights {
        list.item([#h])
      }
    }
    if idx < education.len() - 1 {
      v(0.35em)
    }
  }
}

#let render-skills(skills) = {
  let non_empty = skills.filter(s => s.items.len() > 0)
  if non_empty.len() == 0 { return }
  section-heading(labels.skills)
  for cat in non_empty {
    [#strong(cat.category + ":") #cat.items.join(", ")]
    linebreak()
  }
}

#render-header(data)

#section-heading(labels.profile)
#data.profile_summary

#for sec in data.section_order {
  if sec == "experience" {
    render-experience(data.experiences)
  } else if sec == "projects" {
    render-projects(data.projects)
  } else if sec == "education" {
    render-education(data.education)
  } else if sec == "skills" {
    render-skills(data.skills)
  }
}

#if data.certifications.len() > 0 {
  section-heading(labels.certifications)
  for cert in data.certifications {
    list.item([#cert])
  }
}

#if data.languages_spoken.len() > 0 {
  section-heading(labels.languages)
  [#data.languages_spoken.join("  •  ")]
}
