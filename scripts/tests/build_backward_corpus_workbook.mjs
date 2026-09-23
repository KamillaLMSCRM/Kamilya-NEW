// Rebuild the synthetic two-sheet source fixture. No client data or formulas.
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const output = process.argv[2];
if (!output || !output.endsWith("collections.xlsx")) {
  throw new Error("Pass the exact collections.xlsx fixture path");
}

const workbook = Workbook.create();
const primary = workbook.worksheets.add("Коллекции");
primary.getRange("A1:C4").values = [
  ["Поле", "Север", "Берег"],
  ["Назначение", "Для прихожей", "Для спальни"],
  ["Материал фасада", "МДФ", "ЛДСП"],
  ["Особенность", "Зеркало в комплекте", "Ящики полного выдвижения"],
];
const auxiliary = workbook.worksheets.add("Номенклатура");
auxiliary.getRange("A1:D4").values = [
  ["Артикул", "Наименование", "Коллекция", "Остаток"],
  ["N-001", "Шкаф 80 см", "Север", 4],
  ["N-002", "Вешалка 60 см", "Север", 2],
  ["B-001", "Комод 120 см", "Берег", 3],
];
for (const sheet of [primary, auxiliary]) {
  sheet.showGridLines = false;
  sheet.getUsedRange().format.font = { name: "Arial", size: 10 };
  sheet.getRange(sheet === primary ? "A1:C1" : "A1:D1").format = {
    fill: "#20334D",
    font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
  };
  sheet.getUsedRange().format.autofitColumns();
}
primary.getRange("A:A").format.columnWidth = 23;
primary.getRange("B:B").format.columnWidth = 33;
primary.getRange("C:C").format.columnWidth = 34;
auxiliary.getRange("A:A").format.columnWidth = 15;
auxiliary.getRange("B:B").format.columnWidth = 24;
auxiliary.getRange("C:C").format.columnWidth = 17;
auxiliary.getRange("D:D").format.columnWidth = 14;
workbook.recalculate();
const inspection = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 1200,
});
process.stdout.write(`${inspection.ndjson}\n`);
const preview = await workbook.render({
  sheetName: "Коллекции", range: "A1:C4", scale: 2, format: "png",
});
await fs.writeFile(path.join(path.dirname(output), "collections-preview.png"),
  new Uint8Array(await preview.arrayBuffer()));
const auxiliaryPreview = await workbook.render({
  sheetName: "Номенклатура", range: "A1:D4", scale: 2, format: "png",
});
await fs.writeFile(path.join(path.dirname(output), "catalog-preview.png"),
  new Uint8Array(await auxiliaryPreview.arrayBuffer()));
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(output);
