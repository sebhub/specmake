% SPDX-License-Identifier: CC-BY-SA-4.0

% Copyright (C) 2023 embedded brains GmbH & Co. KG

@`.:/push-enabled-by:sphinx-builder`
This is enabled.
@`.:/push-enabled-by:not: sphinx-builder`
This is disabled.
@`.:/pop-enabled-by` is no marker.
${.:/pop-enabled-by} is no marker.
This is disabled, too.
@`.:/pop-enabled-by`
@`.:/pop-enabled-by`
${.:/push-enabled-by:and: [sphinx-builder, {not: {not: sphinx-builder}}]}
${.:/push-enabled-by:not: sphinx-builder}
This is disabled.
${.:/pop-enabled-by}
${.:/document-html-footer}
${.:/document-latex-copyright}
${.:/document-latex-footer-right}
${.:/document-latex-geometry}
${.:/document-latex-header-left}
${.:/document-latex-sphinxsetup}
${.:/document-latex-title}
${.:/document-normal-title}
${.:/document-release}
${.:/document-title-page-title}
${/glossary/term:/term}
${/glossary/term:/plural}
${/glossary/target:/term}
text
${/rtems/if/func:/name}
text
${/rtems/if/define-disabled:/name}
text
${.:/spec}
${.:/sections:1:section}
text
${/pkg/source/doc-section:/ref}
text
${/pkg/source/doc-subsection:/ref}
text
${.:/document-elements:2:element}
${.:/document-elements:0:element-2-and-3}
${.:/pop-enabled-by}
text
${.:/cite}
text
${.:/cite-long}
text
${.:/bibtex-entries}
text
${.:/item-files:/pkg/component}
text
${.:/item-files:/pkg/*,types=pkg/component/generic+pkg/component/rtems,prologue=Prologue,epilogue=Epilogue,empty=Empty}
text
${.:/item-files:/pkg/*,types=pkg/component/generic,flat=1}
text
${.:/item-files:/does/not/exist,prologue=Prologue,epilogue=Epilogue,empty=Empty}
text
${.:/item-files:/does/not/exist,prologue=Prologue,epilogue=Epilogue,empty=Empty,flat=1}
text
${.:/item-files:/pkg/*/component,children=input+resource}
text
${.:/item-files:/pkg/*/component,parents=input,types=pkg/component/generic}
text
${.:/item-files:/pkg/component,children=input,types=pkg/component/generic}
text
${.:/item-files:/pkg/source/empty,parents=input}
text
${.:/item-files:/spec/links,parents=spec-member}
text
