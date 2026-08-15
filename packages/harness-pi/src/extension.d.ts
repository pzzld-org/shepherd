import type { ExtensionAPI } from "./pi-types";

export interface ExtensionOptions {
  componentModule?: string;
  shepherdBin?: string;
}

export default function shepherdGuardExtension(
  pi: ExtensionAPI,
  options?: ExtensionOptions,
): Promise<void>;
