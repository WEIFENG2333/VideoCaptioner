Rem This batch file will update all .ts() translation strings in app folder.
Rem If you install QT in different location, change it accordingly.
C:\Qt\Tools\QtDesignStudio\qt6_design_studio_reduced_version\bin\lupdate -extensions py -noobsolete .\app\ -ts .\resource\translations\VideoCaptioner_en_US.ts
C:\Qt\Tools\QtDesignStudio\qt6_design_studio_reduced_version\bin\lupdate -extensions py -noobsolete .\app\ -ts .\resource\translations\VideoCaptioner_zh_CN.ts