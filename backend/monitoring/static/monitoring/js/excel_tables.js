"use strict";

function initialiseExcelTable(table) {
  const shell = table.closest("[data-excel-table-shell]");
  const card = table.closest("section");
  const toolbar = card?.querySelector("[data-excel-toolbar]");
  const copyButton = toolbar?.querySelector("[data-excel-copy]");
  const status = toolbar?.querySelector("[data-excel-status]");
  const columnHeaders = Array.from(
    table.querySelectorAll("thead th:not(.excel-table-corner)")
  );
  const rowHeaders = Array.from(
    table.querySelectorAll("tbody .excel-table-row-number")
  );
  const rows = Array.from(table.tBodies[0]?.rows || []);
  const cells = rows.map((row) =>
    Array.from(row.cells).filter(
      (cell) => !cell.classList.contains("excel-table-row-number")
    )
  );

  if (!shell || !toolbar || !copyButton || !status || cells.length === 0) {
    return;
  }

  const defaultStatus = status.textContent.trim();
  let anchor = null;
  let range = null;
  let selecting = false;

  function cellText(cell) {
    return cell.innerText.replace(/\s+/g, " ").trim();
  }

  function coordinatesFor(cell) {
    for (let row = 0; row < cells.length; row += 1) {
      const column = cells[row].indexOf(cell);

      if (column !== -1) {
        return { row, column };
      }
    }

    return null;
  }

  function normaliseRange(start, end) {
    return {
      firstRow: Math.min(start.row, end.row),
      lastRow: Math.max(start.row, end.row),
      firstColumn: Math.min(start.column, end.column),
      lastColumn: Math.max(start.column, end.column),
    };
  }

  function selectedCount() {
    if (!range) {
      return 0;
    }

    return (
      (range.lastRow - range.firstRow + 1) *
      (range.lastColumn - range.firstColumn + 1)
    );
  }

  function renderSelection(message) {
    table.querySelectorAll(".is-selected").forEach((element) => {
      element.classList.remove("is-selected");
    });
    table.querySelectorAll(".is-selection-anchor").forEach((element) => {
      element.classList.remove("is-selection-anchor");
    });

    if (!range) {
      copyButton.disabled = true;
      status.textContent = defaultStatus;
      return;
    }

    for (let row = range.firstRow; row <= range.lastRow; row += 1) {
      for (
        let column = range.firstColumn;
        column <= range.lastColumn;
        column += 1
      ) {
        cells[row]?.[column]?.classList.add("is-selected");
      }
    }

    if (
      range.firstColumn === 0 &&
      range.lastColumn === columnHeaders.length - 1
    ) {
      for (let row = range.firstRow; row <= range.lastRow; row += 1) {
        rowHeaders[row]?.classList.add("is-selected");
      }
    }

    if (
      range.firstRow === 0 &&
      range.lastRow === cells.length - 1
    ) {
      for (
        let column = range.firstColumn;
        column <= range.lastColumn;
        column += 1
      ) {
        columnHeaders[column]?.classList.add("is-selected");
      }
    }

    cells[anchor?.row]?.[anchor?.column]?.classList.add(
      "is-selection-anchor"
    );
    copyButton.disabled = false;
    status.textContent = message || `${selectedCount()} cells selected`;
  }

  function select(start, end, message) {
    anchor = start;
    range = normaliseRange(start, end);
    renderSelection(message);
  }

  function tabSeparatedSelection() {
    const selectedRows = [];

    for (let row = range.firstRow; row <= range.lastRow; row += 1) {
      const selectedColumns = [];

      for (
        let column = range.firstColumn;
        column <= range.lastColumn;
        column += 1
      ) {
        selectedColumns.push(cellText(cells[row][column]));
      }

      selectedRows.push(selectedColumns.join("\t"));
    }

    return selectedRows.join("\n");
  }

  async function writeToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand("copy");
    textArea.remove();
  }

  async function copySelection() {
    if (!range) {
      return;
    }

    try {
      await writeToClipboard(tabSeparatedSelection());
      status.textContent = `${selectedCount()} cells copied to clipboard`;
    } catch (error) {
      status.textContent = "Copy failed. Select the cells and try again.";
    }
  }

  columnHeaders.forEach((header, column) => {
    header.tabIndex = 0;
    header.addEventListener("click", () => {
      select(
        { row: 0, column },
        { row: cells.length - 1, column },
        `Column ${header.textContent.trim()} selected`
      );
    });
  });

  rowHeaders.forEach((header, row) => {
    header.tabIndex = 0;
    header.addEventListener("click", () => {
      select(
        { row, column: 0 },
        { row, column: cells[row].length - 1 },
        `Row ${row + 1} selected`
      );
    });
  });

  const corner = table.querySelector(".excel-table-corner");

  if (corner) {
    corner.tabIndex = 0;
    corner.addEventListener("click", () => {
      select(
        { row: 0, column: 0 },
        {
          row: cells.length - 1,
          column: columnHeaders.length - 1,
        },
        `${cells.length * columnHeaders.length} cells selected`
      );
    });
  }

  cells.flat().forEach((cell) => {
    cell.tabIndex = 0;

    cell.addEventListener("mousedown", (event) => {
      if (event.button !== 0) {
        return;
      }

      const coordinates = coordinatesFor(cell);

      if (!coordinates) {
        return;
      }

      event.preventDefault();
      selecting = true;
      table.classList.add("is-selecting");

      if (event.shiftKey && anchor) {
        range = normaliseRange(anchor, coordinates);
        renderSelection();
        return;
      }

      select(coordinates, coordinates, "1 cell selected");
      cell.focus({ preventScroll: true });
    });

    cell.addEventListener("mouseenter", () => {
      if (!selecting || !anchor) {
        return;
      }

      const coordinates = coordinatesFor(cell);

      if (coordinates) {
        range = normaliseRange(anchor, coordinates);
        renderSelection();
      }
    });

    cell.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }

      event.preventDefault();
      const coordinates = coordinatesFor(cell);

      if (!coordinates) {
        return;
      }

      if (event.shiftKey && anchor) {
        range = normaliseRange(anchor, coordinates);
        renderSelection();
      } else {
        select(coordinates, coordinates, "1 cell selected");
      }
    });
  });

  document.addEventListener("mouseup", () => {
    selecting = false;
    table.classList.remove("is-selecting");
  });

  copyButton.addEventListener("click", copySelection);

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isFormControl =
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target?.isContentEditable;

    if (
      range &&
      (event.ctrlKey || event.metaKey) &&
      event.key.toLowerCase() === "c" &&
      !isFormControl &&
      (table.contains(document.activeElement) ||
        toolbar.contains(document.activeElement))
    ) {
      event.preventDefault();
      copySelection();
    }
  });
}

function initialiseExcelTables() {
  document.querySelectorAll("[data-excel-table]").forEach(
    initialiseExcelTable
  );
}

document.addEventListener("DOMContentLoaded", initialiseExcelTables);
