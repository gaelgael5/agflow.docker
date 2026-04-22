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
  async getVariables(id: string): Promise<ProductVariablesResult> {
    return (await api.get<ProductVariablesResult>(`/admin/products/${id}/variables`)).data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/products/${id}`);
  },
};

export interface ProductVariable {
  name: string;
  description: string;
  type: "variable" | "secret";
  syntax: string;
  required: boolean;
  default: string;
  generate?: string | null;
  undeclared?: boolean;
}

export interface SharedDep {
  name: string;
  property: string;
  syntax: string;
}

export interface ProductConnector {
  name: string;
  description: string;
  package: string;
  runtime: string;
  transport: string;
  status: string;
  env: Record<string, string>;
}

export interface ProductComputed {
  path: string;
  description: string;
}

export interface ProductApiDef {
  source: string;
  url: string;
  base_url: string;
  auth_header: string;
  auth_prefix: string;
  auth_secret_ref: string;
}

export interface ProductService {
  id: string;
  image: string;
  ports: number[];
  requires_services: string[];
}

export interface ProductVariablesResult {
  product_id: string;
  variables: ProductVariable[];
  connectors: ProductConnector[];
  computed: ProductComputed[];
  api: ProductApiDef | null;
  services: ProductService[];
  shared_deps: SharedDep[];
}
