export type Kind = "sftp" | "ftps" | "s3";

export interface Connection {
  id: string;
  name: string;
  kind: Kind;
  config: Record<string, string>;
  has_credentials: boolean;
  created_at: string;
  updated_at: string;
}
