<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { localizerStore, processingStore, TaskStatus, type Workflow } from "../stores";
    import { createRender, createTable, Render, Subscribe } from "svelte-headless-table";
    import { addPagination, addSortBy } from "svelte-headless-table/plugins";
    import { Button } from "$lib/components/ui/button";
    import { readable } from "svelte/store";
    import * as Table from "$lib/components/ui/table";
    import ProcessingTableActions from "./ProcessingTableActions.svelte";
    import LoadingIndicator from "./LoadingIndicator.svelte";
    import ArrowUpDownSvg from "../svg/arrowUpDown.svelte";
    import Image from "./Image.svelte";

    let isLoading: boolean = false;
    const onLoading = (loading: boolean) => {
        isLoading = loading;
    };
    const getRuntime = (value: number): string => {
        const valueSec = value / 1000;
        const mins = Math.floor(valueSec / 60);
        const secs = valueSec % 60;
        if (mins) {
            return `${mins}m ${secs.toFixed(2)}s`;
        } else {
            return `${secs.toFixed(2)}s`;
        }
    };

    const getFileSize = (value = 0): string => {
        if (value < 1000 * 1000) {
            const kB = value / 1000;
            return `${kB.toFixed(2)} kB`;
        } else if (value < 1000 * 1000 * 1000) {
            const MB = value / 1000 / 1000;
            return `${MB.toFixed(2)} MB`;
        } else if (value < 1000 * 1000 * 1000 * 1000) {
            const GB = value / 1000 / 1000 / 1000;
            return `${GB.toFixed(2)} GB`;
        } else {
            const TB = value / 1000 / 1000 / 1000 / 1000;
            return `${TB.toFixed(2)} TB`;
        }
    };

    const initialPageSize: number = 10;
    const getRowEnd = (pageIndex: number) => {
        const numRows = $processingStore.value.length;
        const numPages = Math.floor(numRows / initialPageSize);

        if (pageIndex < numPages) {
            return (pageIndex + 1) * initialPageSize;
        } else {
            return numPages * initialPageSize + (numRows % initialPageSize);
        }
    };

    const getStatusIcon = (status: TaskStatus) => {
        switch (status) {
            case TaskStatus.notStarted:
                return "";
            case TaskStatus.active:
                return "⌛";
            case TaskStatus.completed:
                return "✅";
            case TaskStatus.failed:
                return "❌";
        }
    };

    $: table = createTable(readable($processingStore.value), {
        page: addPagination({
            initialPageSize,
        }),
        sort: addSortBy(),
    });
    $: columns = table.createColumns([
        table.column({
            id: "action",
            accessor: (row: Workflow) => ({ id: row.metadata.id, name: row.metadata.name }),
            header: "",
            cell: ({ value }) => {
                return createRender(ProcessingTableActions, {
                    id: value.id,
                    name: value.name,
                    onLoading,
                });
            },
            plugins: {
                sort: {
                    disable: true,
                },
            },
        }),
        table.column({
            id: "name",
            accessor: (row: Workflow) => row.metadata.name ?? "",
            header: "Name",
        }),
        table.column({
            id: "thumbnail",
            accessor: (row: Workflow) => row.metadata.id,
            header: "Thumbnail",
            cell: ({ value }) => {
                return createRender(Image, {
                    src: `/maps/${value}/thumbnail`,
                });
            },
            plugins: {
                sort: {
                    disable: true,
                },
            },
        }),
        table.column({
            id: "id",
            accessor: (row: Workflow) => {
                // find the last hloc map ID, all hloc tasks start with "(" character
                const lastMapId = [...row.stages.entries()].findLast(([taskId, _taskDescription]) => {
                    return taskId.startsWith("(");
                })?.[1].mapId;

                return "Dataset ID:\n" + row.metadata.id + (lastMapId && `\nMap ID:\n${lastMapId}`);
            },
            header: "ID",
        }),
        table.column({
            id: "file",
            accessor: (row: Workflow) => row.metadata.zip,
            header: "File",
        }),

        table.column({
            id: "size",
            accessor: (row: Workflow) => getFileSize(row.metadata.size),
            header: "Size",
        }),
        table.column({
            id: "status",
            accessor: (row: Workflow) => {
                const tasks = [...row.stages.values()];
                return tasks
                    .map((taskDescription) => {
                        let time = taskDescription.startTime
                            ? `${new Date(taskDescription.startTime).toLocaleString()} + ${getRuntime(taskDescription.runTime!)}`
                            : "";
                        let isCompleted = taskDescription.status === TaskStatus.completed;
                        let taskName;
                        if (taskDescription.mapId) {
                            const shortMapId = taskDescription.mapId.substring(0, 8);
                            taskName = `(${shortMapId}) ${taskDescription.type}`;
                        } else {
                            taskName = taskDescription.type;
                        }
                        let status = `${taskName}: ${taskDescription.status} ${getStatusIcon(taskDescription.status)} ${isCompleted ? " [ " + time + " ]" : ""}`;
                        return status;
                    })
                    .join("\n");
            },
            header: "Status",
        }),
        table.column({
            id: "time",
            accessor: (row: Workflow) => {
                let entries = [...row.stages.values()].filter((task) => task.startTime);
                let last = entries.at(-1);
                if (last) {
                    return last.startTime ?? 0;
                } else {
                    return 0;
                }
            },
            header: "Start Time",
            cell: ({ value }) => {
                return new Date(value).toLocaleString();
            },
        }),
        table.column({
            id: "elapsedTime",
            accessor: (row: Workflow) => {
                return [...row.stages.values()]
                    .map((stage) => stage.runTime ?? 0)
                    .reduce((prevTime, totalTime) => prevTime + totalTime, 0);
            },
            header: "Elapsed Time",
            cell: ({ value }) => getRuntime(value),
        }),
    ]);

    $: tableObject = table.createViewModel(columns);
    $: headerRows = tableObject.headerRows;
    $: pageRows = tableObject.pageRows;
    $: tableAttrs = tableObject.tableAttrs;
    $: tableBodyAttrs = tableObject.tableBodyAttrs;
    $: pluginStates = tableObject.pluginStates;
    $: hasNextPage = pluginStates.page.hasNextPage;
    $: hasPreviousPage = pluginStates.page.hasPreviousPage;
    $: pageIndex = pluginStates.page.pageIndex;
    $: pageSize = pluginStates.page.pageSize;

    //$: console.log("$processingStore.value", $processingStore.value);
</script>

<div class="root">
    {#if isLoading}
        <LoadingIndicator />
    {/if}
    <div class="rounded-md border">
        <Table.Root {...$tableAttrs}>
            <Table.Header>
                {#each $headerRows as headerRow}
                    <Subscribe rowAttrs={headerRow.attrs()}>
                        <Table.Row>
                            {#each headerRow.cells as cell (cell.id)}
                                <Subscribe attrs={cell.attrs()} let:attrs props={cell.props()} let:props>
                                    <Table.Head {...attrs}>
                                        {#if cell.id === "action"}
                                            <Render of={cell.render()} />
                                        {:else}
                                            <Button variant="ghost" on:click={props.sort.toggle}>
                                                <Render of={cell.render()} />
                                                <ArrowUpDownSvg class={"ml-2 h-4 w-4"} />
                                            </Button>
                                        {/if}
                                    </Table.Head>
                                </Subscribe>
                            {/each}
                        </Table.Row>
                    </Subscribe>
                {/each}
            </Table.Header>
            <Table.Body {...$tableBodyAttrs}>
                {#each $pageRows as row (row.id)}
                    <Subscribe rowAttrs={row.attrs()} let:rowAttrs>
                        <Table.Row
                            {...rowAttrs}
                            style={$localizerStore.selectedMap &&
                            row.cells[3].value.includes($localizerStore.selectedMap)
                                ? "background-color:#aaaaaa44"
                                : ""}
                        >
                            {#each row.cells as cell (cell.id)}
                                <Subscribe attrs={cell.attrs()} let:attrs>
                                    <Table.Cell
                                        {...attrs}
                                        class={cell.id === "id"
                                            ? "text-ellipsis max-w-36 overflow-hidden whitespace-pre"
                                            : ""}
                                        title={cell.id === "id" ? "Triple mouse click to select" : ""}
                                    >
                                        {#if cell.id === "elapsedTime"}
                                            <div class="rightAligned">
                                                <Render of={cell.render()} />
                                            </div>
                                        {:else if cell.id === "status"}
                                            <div class="multiLine">
                                                <Render of={cell.render()} />
                                            </div>
                                        {:else}
                                            <Render of={cell.render()} />
                                        {/if}
                                    </Table.Cell>
                                </Subscribe>
                            {/each}
                        </Table.Row>
                    </Subscribe>
                {/each}
            </Table.Body>
        </Table.Root>
    </div>

    <div class="footer">
        <div class="footerSide" />
        <div class="text-muted-foreground justify-center items-center">
            {"Showing row " +
                ($pageIndex * $pageSize + $processingStore.value.length ? 1 : 0) +
                " to " +
                getRowEnd($pageIndex)}
        </div>
        <div class="flex items-center justify-end space-x-4 py-4 pr-8 footerSide">
            <Button
                variant="outline"
                size="sm"
                on:click={() => ($pageIndex = $pageIndex - 1)}
                disabled={!$hasPreviousPage}>Previous</Button
            >
            <Button
                variant="outline"
                size="sm"
                disabled={!$hasNextPage}
                on:click={() => ($pageIndex = $pageIndex + 1)}>Next</Button
            >
        </div>
    </div>
</div>

<style>
    .root {
        height: 100%;
    }

    .footer {
        display: flex;
        flex-direction: row;
        justify-content: space-between;
        align-items: center;
        font-size: 12px;
    }

    .footerSide {
        width: 200px;
    }

    .multiLine {
        white-space: pre-line;
        padding-left: 16px;
        min-width: 400px;
    }

    .rightAligned {
        height: 60px;
        padding-left: 16px;
        text-align: right;
    }
</style>
