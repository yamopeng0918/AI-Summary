export function homePath(baseUrl: string): string {
  return baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`;
}

export function summaryPath(baseUrl: string, id: string): string {
  return `${homePath(baseUrl)}summaries/${encodeURIComponent(id)}/`;
}
