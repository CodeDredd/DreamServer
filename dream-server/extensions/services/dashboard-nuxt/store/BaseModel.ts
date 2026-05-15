import { Model } from 'pinia-orm'

/**
 * Gemeinsame Basisklasse fuer alle Pinia-ORM-Models im Dashboard.
 *
 * Konvention 1:1 vom Referenz-Projekt
 * (`futtertieraerztin/website/store/BaseModel.ts`):
 *
 *   - Models leben unter `store/models/<Name>.ts` (eine Datei pro Model).
 *   - Felder werden ueber Decorators aus `pinia-orm/decorators` definiert
 *     (`@Uid()`, `@Str('')`, `@Num(0)`, `@Bool(false)`, `@Attr({})`, …),
 *     nicht ueber das alte `static fields()`-Pattern.
 *   - Persist-Optionen koennen hier zentral aktiviert werden, sobald
 *     wir `pinia-plugin-persistedstate` einbinden.
 */
export default class BaseModel extends Model {
  // static piniaOptions = { persist: true }
}

