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
  recipe_yaml: string;
}

export interface ProductCreatePayload {
  slug: string;
  display_name: string;
  description?: string;
  category?: string;
  tags?: string[];
  recipe_yaml?: string;
}

export interface ProductUpdatePayload {
  display_name?: string;
  description?: string;
  category?: string;
  tags?: string[];
}

export const productsApi = {
  async list(): Promise<ProductSummary[]> {
    return (await api.get<ProductSummary[]>("/admin/products")).data;
  },
  async get(id: string): Promise<ProductDetail> {
    return (await api.get<ProductDetail>(`/admin/products/${id}`)).data;
  },
  async create(p: ProductCreatePayload): Promise<ProductSummary> {
    return (await api.post<ProductSummary>("/admin/products", p)).data;
  },
  async update(id: string, p: ProductUpdatePayload): Promise<ProductSummary> {
    return (await api.put<ProductSummary>(`/admin/products/${id}`, p)).data;
  },
  async updateRecipe(id: string, recipeYaml: string): Promise<ProductDetail> {
    return (await api.put<ProductDetail>(`/admin/products/${id}/recipe`, { recipe_yaml: recipeYaml })).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/products/${id}`);
  },
};
