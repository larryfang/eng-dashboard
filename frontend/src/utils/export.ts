function escapeCsvCell(value: unknown): string {
  const text = value == null ? '' : String(value)
  if (/[",\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

export function downloadCsv(filename: string, rows: Array<Record<string, unknown>>) {
  if (rows.length === 0) return

  const columns = Array.from(
    rows.reduce((keys, row) => {
      for (const key of Object.keys(row)) keys.add(key)
      return keys
    }, new Set<string>()),
  )

  const lines = [
    columns.map(escapeCsvCell).join(','),
    ...rows.map(row => columns.map(column => escapeCsvCell(row[column])).join(',')),
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function downloadText(filename: string, content: string, mimeType = 'text/plain;charset=utf-8;') {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function printHtmlDocument(title: string, html: string) {
  const popup = window.open('', '_blank', 'noopener,noreferrer,width=1200,height=900')
  if (!popup) return

  popup.document.open()
  popup.document.write(`
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>${title}</title>
        <style>
          body { margin: 0; font-family: Georgia, serif; background: #ffffff; color: #111827; }
          @page { size: A4; margin: 16mm; }
          @media print { .no-print { display: none; } }
        </style>
      </head>
      <body>
        ${html}
      </body>
    </html>
  `)
  popup.document.close()
  popup.focus()
  popup.print()
}
