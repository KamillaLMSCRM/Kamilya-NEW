// Rebuild the synthetic two-sheet source fixture. No client data or formulas.
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const output = process.argv[2];
if (!output || !["collections.xlsx", "expanded_collections.xlsx"].some(name => output.endsWith(name))) {
  throw new Error("Pass the exact collections.xlsx or expanded_collections.xlsx fixture path");
}

const expanded = output.endsWith("expanded_collections.xlsx");
const workbook = Workbook.create();
const primary = workbook.worksheets.add("Коллекции");
if (expanded) {
  primary.getRange("A1:D6").values = [
    ["Поле", "Север", "Берег", "Риф"],
    ["Назначение", "Для прихожей", "Для спальни", "Для гостиной"],
    ["Материал фасада", "МДФ", "ЛДСП", "Шпон дуба"],
    ["Особенность", "Зеркало в комплекте", "Ящики полного выдвижения", "Открытые полки"],
    ["Цвет", "Белый", "Графит", "Натуральный дуб"],
    ["Гарантия", "24 месяца", "18 месяцев", "24 месяца"],
  ];
} else {
  primary.getRange("A1:C4").values = [
    ["Поле", "Север", "Берег"],
    ["Назначение", "Для прихожей", "Для спальни"],
    ["Материал фасада", "МДФ", "ЛДСП"],
    ["Особенность", "Зеркало в комплекте", "Ящики полного выдвижения"],
  ];
}
const auxiliary = workbook.worksheets.add("Номенклатура");
auxiliary.getRange(expanded ? "A1:D6" : "A1:D4").values = expanded ? [
  ["Артикул", "Наименование", "Коллекция", "Остаток"],
  ["N-001", "Шкаф 80 см", "Север", 4],
  ["N-002", "Вешалка 60 см", "Север", 2],
  ["B-001", "Комод 120 см", "Берег", 3],
  ["R-001", "Стеллаж 90 см", "Риф", 5],
  ["R-002", "Тумба 60 см", "Риф", 1],
] : [
  ["Артикул", "Наименование", "Коллекция", "Остаток"],
  ["N-001", "Шкаф 80 см", "Север", 4],
  ["N-002", "Вешалка 60 см", "Север", 2],
  ["B-001", "Комод 120 см", "Берег", 3],
];
for (const sheet of [primary, auxiliary]) {
  sheet.showGridLines = false;
  sheet.getUsedRange().format.font = { name: "Arial", size: 10 };
  sheet.getRange(sheet === primary && !expanded ? "A1:C1" : "A1:D1").format = {
    fill: "#20334D",
    font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
  };
  sheet.getUsedRange().format.autofitColumns();
}
primary.getRange("A:A").format.columnWidth = 23;
primary.getRange("B:B").format.columnWidth = 33;
primary.getRange("C:C").format.columnWidth = 34;
if (expanded) primary.getRange("D:D").format.columnWidth = 31;
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
  sheetName: "Коллекции", range: expanded ? "A1:D6" : "A1:C4", scale: 2, format: "png",
});
await fs.writeFile(path.join(path.dirname(output), expanded ? "expanded-collections-preview.png" : "collections-preview.png"),
  new Uint8Array(await preview.arrayBuffer()));
const auxiliaryPreview = await workbook.render({
  sheetName: "Номенклатура", range: expanded ? "A1:D6" : "A1:D4", scale: 2, format: "png",
});
await fs.writeFile(path.join(path.dirname(output), expanded ? "expanded-catalog-preview.png" : "catalog-preview.png"),
  new Uint8Array(await auxiliaryPreview.arrayBuffer()));
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(output);
