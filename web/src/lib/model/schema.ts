import type { Document, JsonObject, JsonValue } from "@/lib/api/types";
import { isPlainObject } from "./format";

/** The schema id a reference names: "Foo", "#/schemas/Foo" or {"$ref": "Foo"}. */
export function schemaRefId(ref: JsonValue | undefined): string | null {
  if (typeof ref === "string") return ref.replace(/^#\/schemas\//, "");
  if (isPlainObject(ref) && typeof ref.$ref === "string" && Object.keys(ref).length === 1) {
    return ref.$ref.replace(/^#\/schemas\//, "");
  }
  return null;
}

/** Resolves a schema reference to its schema object, following named references. */
export function resolveSchema(doc: Document, ref: JsonValue | undefined): JsonObject | null {
  let cur: JsonValue | undefined = ref;
  for (let depth = 0; depth < 16; depth++) {
    const id = schemaRefId(cur);
    if (id !== null) {
      const s = doc.schemas.find((x) => x.id === id);
      if (!s) return null;
      cur = s.schema;
      continue;
    }
    return isPlainObject(cur) ? cur : null;
  }
  return null;
}

export interface SchemaField {
  name: string;
  type: string;
  required: boolean;
  ref?: string;
  note?: string;
}

/** Flattens an object schema's top-level properties for a compact table. */
export function schemaFields(schema: JsonObject | null): SchemaField[] {
  if (!schema || !isPlainObject(schema.properties)) return [];
  const req = Array.isArray(schema.required) ? schema.required.filter((x): x is string => typeof x === "string") : [];
  return Object.entries(schema.properties)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, p]) => {
      const ref = schemaRefId(p) ?? undefined;
      const obj = isPlainObject(p) ? p : {};
      let type = typeof obj.type === "string" ? obj.type : ref ? ref : "any";
      if (type === "array" && isPlainObject(obj.items)) {
        const itemRef = schemaRefId(obj.items);
        const itemType = itemRef ?? (typeof obj.items.type === "string" ? obj.items.type : "any");
        type = `${itemType}[]`;
      }
      const notes: string[] = [];
      if (Array.isArray(obj.enum)) notes.push(obj.enum.map((e) => JSON.stringify(e)).join(" | "));
      if (typeof obj.format === "string") notes.push(obj.format);
      if (obj.default !== undefined) notes.push(`default ${JSON.stringify(obj.default)}`);
      if (typeof obj.minimum === "number" || typeof obj.maximum === "number") {
        notes.push(`${obj.minimum ?? "…"}..${obj.maximum ?? "…"}`);
      }
      return { name, type, required: req.includes(name), ref, note: notes.join(" · ") || undefined };
    });
}
