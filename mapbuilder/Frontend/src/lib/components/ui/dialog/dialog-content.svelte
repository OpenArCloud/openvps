<script lang="ts">
	import { Dialog as DialogPrimitive } from "bits-ui";
	import Cross2 from "svelte-radix/Cross2.svelte";
	import * as Dialog from "./index.js";
	import { cn, flyAndScale } from "$lib/utils.js";

	type $$Props = DialogPrimitive.ContentProps;

	let className: $$Props["class"] = undefined;
	export let transition: $$Props["transition"] = flyAndScale;
	export let transitionConfig: $$Props["transitionConfig"] = {
		duration: 200,
	};
	export { className as class };
</script>

<Dialog.Portal>
	<Dialog.Overlay />
	<DialogPrimitive.Content
		{transition}
		{transitionConfig}
		class={cn(
			"bg-background fixed left-[50%] top-4 bottom-4 z-50 grid box-border min-w-0 w-[calc(100%-1rem)] max-w-[calc(100%-1rem)] max-h-[calc(100dvh-2rem)] translate-x-[-50%] translate-y-0 gap-4 overflow-x-hidden overflow-y-auto border p-6 shadow-lg sm:left-[50%] sm:top-[50%] sm:right-auto sm:bottom-auto sm:w-full sm:max-w-lg sm:max-h-none sm:translate-x-[-50%] sm:translate-y-[-50%] sm:rounded-lg md:w-full",
			className
		)}
		{...$$restProps}
	>
		<slot />
		<DialogPrimitive.Close
			class="ring-offset-background focus:ring-ring data-[state=open]:bg-accent data-[state=open]:text-muted-foreground absolute right-4 top-4 rounded-sm opacity-70 transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:pointer-events-none"
		>
			<Cross2 class="h-4 w-4" />
			<span class="sr-only">Close</span>
		</DialogPrimitive.Close>
	</DialogPrimitive.Content>
</Dialog.Portal>
