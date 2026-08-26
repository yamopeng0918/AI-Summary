import type { SummaryRecord } from './summaries';

export interface OgImageContent {
  title: string;
  summary: string;
  category: string;
  source: string;
  sourceType: 'WEB' | 'YOUTUBE' | 'SOCIAL';
}

export function fitOgText(text: string, limits: readonly number[]): string[] {
  const characters = Array.from(text.trim());
  const lines: string[] = [];
  let offset = 0;
  for (const limit of limits) {
    if (offset >= characters.length) break;
    const remaining = characters.length - offset;
    const take = Math.min(limit, remaining);
    lines.push(characters.slice(offset, offset + take).join(''));
    offset += take;
  }
  if (offset < characters.length && lines.length > 0) {
    const last = lines.length - 1;
    lines[last] = `${Array.from(lines[last]).slice(0, -1).join('')}…`;
  }
  return lines;
}

export function createOgImageContent(record: SummaryRecord): OgImageContent {
  return {
    title: record.title,
    summary: record.summary,
    category: record.category,
    source: record.author?.trim() || new URL(record.canonicalUrl).hostname,
    sourceType: record.sourceType.toUpperCase() as OgImageContent['sourceType'],
  };
}
