import { z } from 'zod';

export const SummaryRecordSchema = z.object({
  schemaVersion: z.literal(1),
  id: z.string(),
  canonicalUrl: z.string().url().max(2083),
  sourceType: z.literal('web'),
  title: z.string(),
  author: z.string().nullable(),
  sourcePublishedAt: z.string().datetime({ offset: true }).nullable(),
  createdAt: z.string().datetime({ offset: true }),
  updatedAt: z.string().datetime({ offset: true }),
  summary: z.string(),
  keyPoints: z.array(z.string()).min(3).max(5),
  category: z.string(),
  tags: z.array(z.string()).min(1).max(5),
  editorial: z.string(),
  status: z.enum(['published', 'archived']),
});

export type SummaryRecord = z.infer<typeof SummaryRecordSchema>;

export function parseSummaryRecord(record: unknown): SummaryRecord {
  return SummaryRecordSchema.parse(record);
}

export function getPublishedSummaries(records: SummaryRecord[]): SummaryRecord[] {
  return records.filter((record) => record.status === 'published');
}

export function filterAndSortSummaries(
  records: SummaryRecord[],
  query: string,
  category: string,
  order: 'newest' | 'oldest',
): SummaryRecord[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();

  return records
    .filter((record) => !category || record.category === category)
    .filter((record) => {
      if (!normalizedQuery) return true;

      return [record.title, record.summary, record.keyPoints.join(' ')]
        .join(' ')
        .toLocaleLowerCase()
        .includes(normalizedQuery);
    })
    .toSorted((first, second) => {
      const difference = Date.parse(second.createdAt) - Date.parse(first.createdAt);
      return order === 'newest' ? difference : -difference;
    });
}

export async function loadPublishedSummaries(): Promise<SummaryRecord[]> {
  const { readdirSync, readFileSync } = await import('node:fs');
  const { fileURLToPath } = await import('node:url');
  const summariesDirectory = fileURLToPath(new URL('../../../data/summaries/', import.meta.url));
  const records = readdirSync(summariesDirectory)
    .filter((fileName) => fileName.endsWith('.json'))
    .map((fileName) => {
      const filePath = new URL(`../../../data/summaries/${fileName}`, import.meta.url);
      return parseSummaryRecord(JSON.parse(readFileSync(filePath, 'utf8')));
    });

  return filterAndSortSummaries(getPublishedSummaries(records), '', '', 'newest');
}
