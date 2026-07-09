import rawArticles from "../data/hyperscaler-news/articles.json";
import rawSources from "../data/hyperscaler-news/sources.json";

export type HyperscalerNewsArticle = {
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

export type HyperscalerNewsPayload = {
  generated_at: string;
  article_count: number;
  articles: HyperscalerNewsArticle[];
};

export type HyperscalerNewsSource = {
  id: string;
  name: string;
  url: string;
  type: "rss" | "html_links";
  status: "ok" | "error";
  error?: string;
  article_count: number;
};

export type HyperscalerNewsSourcesPayload = {
  generated_at: string;
  sources: HyperscalerNewsSource[];
};

const articlePayload = rawArticles as HyperscalerNewsPayload;
const sourcePayload = rawSources as HyperscalerNewsSourcesPayload;

export const hyperscalerNewsGeneratedAt = articlePayload.generated_at;
export const hyperscalerNewsArticles = articlePayload.articles;
export const hyperscalerNewsSources = sourcePayload.sources;

export const hyperscalerNewsSourceFilters = [
  { id: "all", name: "전체" },
  ...hyperscalerNewsSources.map((source) => ({ id: source.id, name: source.name })),
];

export const hyperscalerNewsTags = Array.from(
  new Set(hyperscalerNewsArticles.flatMap((article) => article.tags_ko ?? article.tags)),
).sort();
