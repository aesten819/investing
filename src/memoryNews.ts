import rawArticles from "../data/memory-news/articles.json";
import rawSources from "../data/memory-news/sources.json";

export type MemoryNewsArticle = {
  id: string;
  headline: string;
  headline_ko?: string;
  summary: string;
  summary_ko?: string;
  url: string;
  source: string;
  source_id: string;
  published_at: string;
  tags: string[];
  tags_ko?: string[];
};

export type MemoryNewsPayload = {
  generated_at: string;
  article_count: number;
  articles: MemoryNewsArticle[];
};

export type MemoryNewsSource = {
  id: string;
  name: string;
  url: string;
  status: "ok" | "error";
  error?: string;
  article_count: number;
};

export type MemoryNewsSourcesPayload = {
  generated_at: string;
  sources: MemoryNewsSource[];
};

const articlePayload = rawArticles as MemoryNewsPayload;
const sourcePayload = rawSources as MemoryNewsSourcesPayload;

export const memoryNewsGeneratedAt = articlePayload.generated_at;
export const memoryNewsArticles = articlePayload.articles;
export const memoryNewsSources = sourcePayload.sources;

export const memoryNewsSourceFilters = [
  { id: "all", name: "전체" },
  ...memoryNewsSources.map((source) => ({ id: source.id, name: source.name })),
];

export const memoryNewsTags = Array.from(
  new Set(memoryNewsArticles.flatMap((article) => article.tags_ko ?? article.tags)),
).sort();

export function formatNewsDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function articleHeadline(article: MemoryNewsArticle): string {
  return article.headline_ko || article.headline;
}

export function articleSummary(article: MemoryNewsArticle): string {
  return article.summary_ko || article.summary;
}

export function articleTags(article: MemoryNewsArticle): string[] {
  return article.tags_ko?.length ? article.tags_ko : article.tags;
}
