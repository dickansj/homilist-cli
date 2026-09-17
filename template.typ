// @sjml's page geometry and type, with the header rebuilt to carry the
// information already written at the top of each homily.
//
// Page-1 header, top right:
//     Occasion            (bold, omitted when blank -- "Healing Mass")
//     Title               (`title:`, falling back to the scraped lectionary_string)
//     Readings            (`preached:`, falling back to `readings:` minus the psalm)
//     Location · Date     (long-form date, matching the .docx convention)
//     Lectionary N · Variant   (dimmed)
//
// Later pages carry only the page number.

#let horizontalrule = line(start: (25%, 0%), end: (75%, 0%))

// `preached` is the pruned citation line -- what was actually preached on. Until
// it is filled in, the header falls back to the whole liturgy of the word, and
// the psalm is the one part of that nobody preaches from. Dropping it here means
// an untrimmed draft still prints a sensible header.
#let without_psalm(citations) = {
	let kept = citations
		.split("; ")
		.filter(c => not c.trim().starts-with("Ps "))
	kept.join("; ")
}

#let date_string = "$date$"
#let (year, month, day) = date_string.split("-").map(int)
#let date_obj = datetime(
	year: year,
	month: month,
	day: day,
)

#set page(
	paper: "us-letter",
	margin: (x: 1in, top: 1in, bottom: 3in),

	header: context {
		set text(size: 12pt)
		let page = counter(page).get().first()

		if page == 1 [
			#align(top)[
				#pad(top: 0.5in)[
					#grid(
						columns: (1fr, auto),
						align(top + left)[#page],
						align(top + right)[
							$if(occasion)$#strong[$occasion$] \$endif$
							$if(title)$$title$$else$$lectionary_string$$endif$ \
							$if(preached)$$preached$$else$#without_psalm("$readings$")$endif$ \
							$location$ · #date_obj.display("[month repr:long] [day padding:none], [year]") \
							#text(fill: luma(45%))[$if(lectionary_number)$Lectionary $lectionary_number$$endif$$if(variant)$ · $variant$$endif$]
						],
					)
				]
			]
		] else [
			#align(top)[
				#pad(top: 0.5in)[
					#align(top + left)[#page]
				]
			]
		]
	},
)

#set text(
	font: "Cambria",
	lang: "en",
	region: "US",
	size: 16pt,
)

#v(0.75in) // make room for first-page header

#set par(
	justify: false,
	leading: .85em,
	spacing: 2em,
)
#show par: it => block(
	breakable: false,
	inset: (left: 1em, right: 2em),
	it.body
)

$body$
