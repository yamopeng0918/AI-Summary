export interface SummaryRecord {
  schemaVersion: 1;
  id: string;
  canonicalUrl: string;
  sourceType: 'web' | 'youtube' | 'social';
  title: string;
  author: string | null;
  sourcePublishedAt: string | null;
  createdAt: string;
  updatedAt: string;
  summary: string;
  keyPoints: string[];
  category: string;
  tags: string[];
  editorial: string;
  status: 'published' | 'archived';
}

export interface SummaryCard {
  dataset: { summaryCard?: string };
  hidden: boolean;
}

export interface SummaryCardContainer<Card extends SummaryCard> {
  append(...nodes: Card[]): void;
}

export function sourceLabel(record: Pick<SummaryRecord, 'author' | 'sourceType'>): string {
  if (record.author) return record.author;

  return {
    youtube: 'YouTube',
    social: '社群貼文',
    web: '公開網頁',
  }[record.sourceType];
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

export function serializeSummaryRecords(records: SummaryRecord[]): string {
  return JSON.stringify(records).replaceAll('<', '\\u003c');
}

export function shouldShowNoResults(visibleCardCount: number): boolean {
  return visibleCardCount === 0;
}

export function reorderSummaryCards<Card extends SummaryCard>(
  container: SummaryCardContainer<Card>,
  cards: Card[],
  records: SummaryRecord[],
  query: string,
  category: string,
  order: 'newest' | 'oldest',
): void {
  const sortedRecords = filterAndSortSummaries(records, query, category, order);
  const visibleIds = new Set(sortedRecords.map((record) => record.id));
  const cardsById = new Map(cards.map((card) => [card.dataset.summaryCard, card]));
  const visibleCards = sortedRecords.flatMap((record) => {
    const card = cardsById.get(record.id);
    return card ? [card] : [];
  });
  const hiddenCards = cards.filter((card) => !visibleIds.has(card.dataset.summaryCard ?? ''));

  cards.forEach((card) => {
    card.hidden = !visibleIds.has(card.dataset.summaryCard ?? '');
  });
  container.append(...visibleCards, ...hiddenCards);
}
