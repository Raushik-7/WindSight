/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Absolute origin of the WindSight API. Leave unset when the frontend is
   * served behind the same origin as the API (Vite proxy / nginx container).
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
