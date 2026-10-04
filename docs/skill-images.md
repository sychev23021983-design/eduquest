# Skill task illustrations

The existing 11 logical task images remain unchanged. The generation manifest
contains the other 267 active tasks, their original text, output paths, upload
URLs and prompts. Images are generated separately with built-in ImageGen, using
the existing illustrated logic cards as a style reference. Each final image is
stored in `assets/skill-images/skill-ID.png` and must be visually reviewed before
attachment. Unknown answers, colors, order and relationships must remain unknown
in the illustration. The knowledge block uses topic headings and scenes; its existing factual paragraphs remain in the application rather than being duplicated in the image. This release does not constitute a factual audit of those paragraphs. Rejected variants are retained outside the Git asset set.

Reviewed set: all IDs 12–278 (267 task images). All images have passed visual QA. Together with the 11 original logic images, all 278 active tasks have illustrations.

## Local installation

Copy only reviewed assets into `data/uploads/images`, then run
`backend/scripts/install_skill_images.py` inside the backend container with the
manifest. The default is a dry run; `--apply` attaches available images after a
SQLite online backup. It refuses changed task text and existing different image
URLs. No task text, hints, answers or progress is rewritten. Existing React views
and nginx `/uploads/` routing already display these images without a rebuild.

## Rollback

For a task in this release, clear `image_url` only if its current value equals
the release's `/uploads/images/skill-ID.png`. Keep files and the SQLite backup.
Do not replace the live database with the backup after newer user activity: that
would also revert progress unrelated to these images.
