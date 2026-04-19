import { api } from "./api";

export interface ProductSummary {
  id: string;
  display_name: string;
  description: string;
  category: string;
  tags: string[];
  min_ram_mb: number;
  config_only: boolean;
  has_openapi: boolean;
  mcp_package_id: string | null;
  recipe_version: string;
}

export interface ProductDetail extends ProductSummary {
  recipe: Record<string, unknown>;
}

export const productsApi = {
  async list(): Promise<ProductSummary[]> {
    return (await api.get<ProductSummary[]>("/admin/products")).data;
  },
  async get(id: string): Promise<ProductDetail> {
    return (await api.get<ProductDetail>(`/admin/products/${id}`)).data;
  },
};
